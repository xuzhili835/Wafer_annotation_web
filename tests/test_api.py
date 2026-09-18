"""API 冒烟:全协作闭环(登录→分配→一致定稿→分歧→第三人→事实多数→平票仲裁→异议→封板→导出)。"""
from __future__ import annotations

import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

os.environ["WAFER_DB"] = os.path.join(os.environ.get("TEMP", "/tmp"), "wafer_test.db")

import importlib

from app import config as cfg

cfg.DB_PATH = __import__("pathlib").Path(os.environ["WAFER_DB"])
cfg.DATA_DIR = __import__("pathlib").Path(os.environ.get("WAFER_TMP_DATA", cfg.DATA_DIR))

import app.db as db_mod

db_mod.DB_PATH = cfg.DB_PATH
db_mod.DATA_DIR = cfg.DATA_DIR
db_mod.TOKENS_FILE = cfg.TOKENS_FILE

import app.main as main_mod

main_mod.DATA_DIR = cfg.DATA_DIR

TOKENS = {m: f"{m}_testtoken" for m in cfg.MEMBERS}


def _make_data(tmp_path, n=12, size=64):
    from PIL import Image
    data = tmp_path / "data"
    train = data / "训练集"
    train.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("L", (size, size), color=i * 30 % 255).save(train / f"img_{i:02d}.png")
    # 产线参照样例(测试集,只读):绝不进 images 表
    # X 目录的图带 2 个 HB 框 → 按框码组织时 HB 样例应能跨目录收集到且排最前
    for code in ("X", "HB"):
        d = data / "测试集" / code
        d.mkdir(parents=True)
        Image.new("L", (size, size), 99).save(d / f"ref_{code}.png")
        extra = ('<object><name>HB</name><bndbox><xmin>30</xmin><ymin>30</ymin>'
                 '<xmax>50</xmax><ymax>50</ymax></bndbox></object>'
                 '<object><name>HB</name><bndbox><xmin>40</xmin><ymin>10</ymin>'
                 '<xmax>55</xmax><ymax>25</ymax></bndbox></object>') if code == "X" else ""
        (d / f"ref_{code}.xml").write_text(
            f'<annotation><size><width>{size}</width><height>{size}</height></size>'
            f'<object><name>{code}</name><bndbox><xmin>1</xmin><ymin>2</ymin>'
            f'<xmax>20</xmax><ymax>21</ymax></bndbox></object>{extra}</annotation>',
            encoding="utf-8")
    return data


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    data = _make_data(tmp_path_factory.mktemp("wafer"))
    cfg.DATA_DIR = data
    db_mod.DATA_DIR = data
    tf = tmp_path_factory.mktemp("tok") / "tokens.txt"
    tf.write_text("\n".join(f"{k}:{v}" for k, v in TOKENS.items()), encoding="utf-8")
    cfg.TOKENS_FILE = tf
    db_mod.TOKENS_FILE = tf
    main_mod.DATA_DIR = data
    if os.path.exists(cfg.DB_PATH):
        os.remove(cfg.DB_PATH)
    from fastapi.testclient import TestClient as TC
    with TC(main_mod.app) as c:
        yield c


def H(name):
    return {"X-Token": TOKENS[name]}


def submit(client, name, stem, boxes, empty=False):
    r = client.post("/api/submit", json={"stem": stem, "boxes": boxes, "is_empty": empty},
                    headers=H(name))
    assert r.status_code == 200, r.text
    return r.json()


def B(code, x0, y0, x1, y1):
    return {"code": code, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def test_login_and_meta(client):
    for name in TOKENS:
        r = client.post("/api/login", json={"token": TOKENS[name]})
        assert r.status_code == 200 and r.json()["name"] == name
    assert client.post("/api/login", json={"token": "bad_xxx"}).status_code == 401
    assert client.get("/api/me", headers=H("hce")).json()["name"] == "hce"
    assert len(client.get("/api/meta").json()["codes"]) == 12


def test_assignment(client):
    r = client.get("/api/queue", headers=H("hce")).json()["queue"]
    assert len(r) == 12
    # 每张图恰好 2 个不同分配人
    conn = db_mod.connect()
    try:
        rows = conn.execute("SELECT assignee_a, assignee_b FROM images").fetchall()
        assert len(rows) == 12
        for row in rows:
            assert row["assignee_a"] != row["assignee_b"]
        counts = {m: 0 for m in TOKENS}
        for row in rows:
            counts[row["assignee_a"]] += 1
            counts[row["assignee_b"]] += 1
        assert max(counts.values()) - min(counts.values()) <= 1
    finally:
        conn.close()


def test_two_agree_auto_final(client):
    r = submit(client, "cmx", "img_00", [B("X", 10, 10, 60, 70)])
    assert not r.get("final_id")
    r = submit(client, "hce", "img_00", [B("X", 12, 11, 61, 69)])  # IoU 很高 → 一致
    assert r.get("final_id")
    rv = client.get("/api/review/img_00", headers=H("cmx")).json()
    assert rv["via"] == "unanimous" and rv["final_id"] == r["final_id"]
    assert len(rv["winners"]) == 2, "一致定稿簇应含两份,不只点亮最早那份"


def test_arbitration_final_scope(client):
    """scope=final 返回已定稿列表(异议入口);默认待决列表不含已定稿。"""
    r = client.get("/api/arbitration?scope=final", headers=H("hce"))
    lst = r.json()["list"]
    assert "img_00" in [o["stem"] for o in lst] and all("round" in o for o in lst)
    r2 = client.get("/api/arbitration", headers=H("hce"))
    assert "img_00" not in [o["stem"] for o in r2.json()["list"]]


def test_conflict_then_third_majority(client):
    submit(client, "cmx", "img_01", [B("BX", 5, 5, 40, 40)])
    r = submit(client, "hce", "img_01", [B("X", 5, 5, 40, 40)])  # 不同码 → 分歧
    assert not r.get("final_id") and r.get("conflict")
    # 第三人 zj 与 cmx 一致 → 事实多数(2/3)自动定稿
    r = submit(client, "zj", "img_01", [B("BX", 6, 6, 41, 40)])
    assert r.get("final_id")
    rv = client.get("/api/review/img_01", headers=H("cmx")).json()
    assert rv["via"] == "majority", "第三人补标 2/3 一致 = 多数一致定稿(非投票)"


def test_vote_settlement_and_tie(client):
    stem = "img_02"
    submit(client, "cmx", stem, [B("KD", 10, 10, 30, 30)])
    r = submit(client, "hce", stem, [B("HS", 10, 10, 30, 30)])
    assert r.get("conflict"), "KD vs HS → 分歧"
    # zj 的 KD 在远处,与 cmx 的 KD 不 match → 三组各 1,无多数
    r = submit(client, "zj", stem, [B("KD", 50, 50, 60, 60)])
    assert not r.get("final_id") and r.get("conflict")
    # zzq 的 KD 与 cmx 的 match → KD_A 组 2 份,但 2 不 > 4/2 → 仍需盲投
    r = submit(client, "zzq", stem, [B("KD", 11, 11, 29, 29)])
    assert not r.get("final_id")
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert len(rv["candidates"]) == 4
    assert all(c["annotator"] is None for c in rv["candidates"]), "定稿前必须匿名"
    kd_a = next(c["id"] for c in rv["candidates"]
                if c["boxes"] and c["boxes"][0]["code"] == "KD" and c["boxes"][0]["x0"] == 10)
    hs_id = next(c["id"] for c in rv["candidates"]
                 if c["boxes"] and c["boxes"][0]["code"] == "HS")
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd_a}, headers=H("cmx"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd_a}, headers=H("hce"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": hs_id}, headers=H("zj"))
    rv = client.get("/api/review/" + stem, headers=H("zj")).json()
    assert rv["final"], "3 票 2:1 多数 → 定稿"
    assert rv["my_vote"] == hs_id
    assert rv["via"] == "vote" and rv["final_id"] == kd_a, "投票定稿,final 指向 kd_a"
    # 定稿后解锁真名
    assert any(c["annotator"] for c in rv["candidates"])


def test_empty_and_dispute_reopen(client):
    submit(client, "cmx", "img_03", [], empty=True)
    r = submit(client, "hce", "img_03", [], empty=True)
    assert r.get("final_id")
    rv = client.get("/api/review/img_03", headers=H("hce")).json()
    assert rv["final"]
    d = client.post("/api/dispute", json={"stem": "img_03", "reason": "再看一眼好像有东西"},
                    headers=H("zj"))
    assert d.status_code == 200 and d.json()["round"] == 2
    assert not client.get("/api/review/img_03", headers=H("hce")).json()["final"]
    d2 = client.post("/api/dispute", json={"stem": "img_03", "reason": "x"}, headers=H("zj"))
    assert d2.status_code == 400, "无理由异议不受理"


def test_revoke_own_only(client):
    r = client.post("/api/revoke/999999", headers=H("cmx"))
    assert r.status_code in (403, 404)
    conn = db_mod.connect()
    try:
        mine = conn.execute("SELECT id FROM annotations WHERE annotator='cmx' ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    r = client.post(f"/api/revoke/{mine['id']}", headers=H("zzq"))
    assert r.status_code == 403
    r = client.post(f"/api/revoke/{mine['id']}", headers=H("cmx"))
    assert r.status_code == 200


def test_seal_and_exports(client):
    for m in ("cmx", "hce", "zj"):
        client.post("/api/seal", headers=H(m))
    s = client.get("/api/seal", headers=H("cmx")).json()
    assert s["sealed"] and s["count"] == 3

    csv_text = client.get("/api/export/annotations.csv", headers=H("cmx")).text
    assert csv_text.count("\n") >= 7 and "annotator" in csv_text
    voted = client.get("/api/export/labels_voted.csv", headers=H("cmx")).text
    assert "img_00" in voted and "final" in voted

    # 导出响应必须 no-store:csv/zip 在 CF 默认边缘缓存名单里,不显式禁缓存会下载到旧数据
    for path in ("/api/export/annotations.csv", "/api/export/labels_voted.csv",
                 "/api/export/voc_xml.zip"):
        r = client.get(path, headers=H("cmx"))
        assert r.headers.get("cache-control") == "private, no-store", path

    zr = client.get("/api/export/voc_xml.zip", headers=H("cmx"))
    zf = zipfile.ZipFile(io.BytesIO(zr.content))
    names = [n for n in zf.namelist() if n.endswith(".xml")]
    assert names, "封板前已定稿图应入包"
    root = ET.fromstring(zf.read(names[0]))
    assert root.tag == "annotation"
    assert root.find("size/width").text == "64"
    objs = root.findall("object")
    assert objs and objs[0].find("name").text in cfg.CODES
    b = objs[0].find("bndbox")
    assert all(b.find(k) is not None for k in ("xmin", "ymin", "xmax", "ymax"))
    assert zr.headers.get("X-Final-Count", "0").isdigit()


def test_reference_prod(client):
    r = client.get("/api/reference_prod", headers=H("hce"))
    assert r.status_code == 200
    codes = r.json()["codes"]
    assert set(codes) == {"X", "HB"}
    x = codes["X"][0]
    assert x["boxes"][0]["code"] == "X" and x["url"].startswith("/api/ref_image/X/")
    # 按框码组织:X 目录图里的 2 个 HB 框也应被 HB 类收集到(跨目录,排在-only-1-框的 HB 图前面)
    hb = codes["HB"]
    assert len(hb) == 2 and hb[0]["url"].startswith("/api/ref_image/X/")
    assert sum(1 for b in hb[0]["boxes"] if b["code"] == "HB") == 2
    img = client.get(x["url"], headers=H("hce"))
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")
    # 路径穿越 / 非法目录名一律 404
    assert client.get("/api/ref_image/X/%2e%2e%2fx.png", headers=H("hce")).status_code == 404
    assert client.get("/api/ref_image/XX/no.png", headers=H("hce")).status_code == 404
    # 未授权拒绝(先清前面用例留下的登录 cookie,模拟无凭据访问)
    client.cookies.clear()
    assert client.get("/api/reference_prod").status_code == 401
    assert client.get(x["url"]).status_code == 401
    # 测试集绝不进标注库(仍 12 张训练图)
    conn = db_mod.connect()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM images").fetchone()["c"] == 12
    finally:
        conn.close()


def test_draft_lenient(client):
    # 草稿宽松:拖拽中间态(过小框)、未知码、空框列表都照存,不报 400
    r = client.post("/api/draft", json={"stem": "img_04", "is_empty": False,
                    "boxes": [B("X", 5, 5, 6, 6), B("XX", 0, 0, 9, 9)]}, headers=H("cmx"))
    assert r.status_code == 200
    assert client.post("/api/draft", json={"stem": "img_04", "boxes": [], "is_empty": False},
                       headers=H("cmx")).status_code == 200
    conn = db_mod.connect()
    try:
        row = conn.execute("SELECT boxes_json FROM drafts WHERE stem='img_04'").fetchone()
    finally:
        conn.close()
    import json as _json
    assert _json.loads(row["boxes_json"]) == [], "最后一次空框草稿应覆盖成功"
    # submit 仍严格:过小框拒绝
    assert client.post("/api/submit", json={"stem": "img_04",
                       "boxes": [B("X", 5, 5, 6, 6)]}, headers=H("cmx")).status_code == 400


def test_validation(client):
    r = client.post("/api/submit", json={"stem": "img_04", "boxes": [], "is_empty": False},
                    headers=H("cmx"))
    assert r.status_code == 400, "有框空提交应报错引导勾选无缺陷"
    r = client.post("/api/submit", json={"stem": "img_04",
                    "boxes": [B("XX", 1, 1, 9, 9)]}, headers=H("cmx"))
    assert r.status_code == 400, "未知代码应拒绝"


# ---------- 回归校准单 2026-09-17(find-bug-skill 独立审查轮追加,全部为已验证行为的回归钉) ----------

def test_image_png_suffix(client):
    r = client.get("/api/image/img_00.webp", headers=H("hce"))
    assert r.status_code == 200, "带后缀的图片 URL 应正常"
    assert r.headers["content-type"].startswith("image/webp"), "默认应回 WebP(体积小一个量级)"
    assert "private" in r.headers.get("cache-control", ""), "必须 private:CF 不得缓存带鉴权的图片"
    r = client.get("/api/image/img_00", headers=H("hce"))
    assert r.status_code == 200, "不带后缀也保持可用"


def test_health_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_me_anonymous_returns_null_not_401(client):
    fresh = TestClient(main_mod.app)
    r = fresh.get("/api/me")
    assert r.status_code == 200 and r.json()["name"] is None, "首访 401 会刷浏览器 console error(回归:me 未登录改返 200)"


def test_logout_clears_cookie(client):
    # cookie 已带 secure 标记(只随 HTTPS 回传):测试须走 https 基址,浏览器端公网即 https
    c = TestClient(main_mod.app, base_url="https://testserver")
    assert c.post("/api/login", json={"token": TOKENS["zj"]}).status_code == 200
    assert c.get("/api/queue").status_code == 200, "登录后 cookie 通道可用"
    c.post("/api/logout")
    assert c.get("/api/queue").status_code == 401, "退出后旧 cookie 必须失效(回归:前端退出必须调 /api/logout)"


def test_unauthorized_matrix(client):
    fresh = TestClient(main_mod.app)
    for p in ("/api/queue", "/api/task/img_00", "/api/review/img_00", "/api/arbitration",
              "/api/seal", "/api/progress", "/api/export/annotations.csv",
              "/api/export/labels_voted.csv", "/api/export/voc_xml.zip", "/api/image/img_00"):
        assert fresh.get(p).status_code == 401, p
    for p in ("/api/submit", "/api/draft", "/api/vote", "/api/dispute", "/api/seal"):
        assert fresh.post(p, json={"stem": "img_00"}).status_code == 401, p


def test_box_validation_matrix(client):
    s = "img_05"

    def post(boxes, empty=False):
        return client.post("/api/submit", json={"stem": s, "boxes": boxes, "is_empty": empty},
                           headers=H("cmx"))

    assert post([B("XX", 1, 1, 9, 9)]).status_code == 400, "未知代码"
    assert post([B("X", 1, 1, 2, 9)]).status_code == 400, "宽 1px 过小"
    assert post([B("X", 60, 10, 10, 40)]).status_code == 200, "倒序坐标应规范化后接受"
    assert post([B("X", -50, -50, 700, 700)]).status_code == 200, "越界坐标应夹紧到图幅"
    assert post([], empty=True).status_code == 200
    assert post([B("X", 10, 10, 20, 20)], empty=True).status_code == 200, "勾选空图时框应被忽略"
    conn = db_mod.connect()
    try:
        row = conn.execute("SELECT boxes_json,is_empty FROM annotations WHERE stem=? ORDER BY id DESC LIMIT 1", (s,)).fetchone()
    finally:
        conn.close()
    assert row["is_empty"] == 1 and json.loads(row["boxes_json"]) == [], "is_empty=true 时框必须丢弃"


def test_submit_unknown_stem(client):
    for bad in ("img_99", "../../etc/passwd"):
        r = client.post("/api/submit", json={"stem": bad, "boxes": [B("X", 1, 1, 9, 9)]},
                        headers=H("cmx"))
        assert r.status_code == 404, bad


def test_vote_upsert_same_round(client):
    stem = "img_04"
    submit(client, "cmx", stem, [B("KD", 10, 10, 30, 30)])
    submit(client, "hce", stem, [B("HS", 40, 40, 60, 60)])
    submit(client, "zj", stem, [B("BX", 1, 1, 20, 20)])
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    kd = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "KD")
    hs = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "HS")
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("cmx"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": hs}, headers=H("cmx"))  # 同人改票
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("hce"))
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert rv["votes"] == 2 and rv["my_vote"] == hs, "同人同轮重复投票应 upsert(改票生效)而非累计"
    assert not rv["final"], "2 票不足 3 票"
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("zj"))
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert rv["final"], "3 票 3:0 → 定稿"


def test_dispute_new_round_ignores_old_votes(client):
    stem = "img_04"
    d = client.post("/api/dispute", json={"stem": stem, "reason": "前一轮投得太快,想再看看"},
                    headers=H("zzq"))
    assert d.status_code == 200 and d.json()["round"] == 2
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert not rv["final"] and rv["round"] == 2
    kd = next(c["id"] for c in rv["candidates"] if c["boxes"] and c["boxes"][0]["code"] == "KD")
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("zzq"))
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert not rv["final"] and rv["votes"] == 1, "第 2 轮只见新票,第 1 轮 3 票自然作废"
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("cmx"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("hce"))
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert rv["final"] and rv["round"] == 2, "第 2 轮重新满 3 票 → 定稿"


def test_vote_revoked_candidate_404(client):
    conn = db_mod.connect()
    try:
        row = conn.execute("SELECT id,stem FROM annotations WHERE revoked=1 LIMIT 1").fetchone()
    finally:
        conn.close()
    r = client.post("/api/vote", json={"stem": row["stem"], "chosen_id": row["id"]}, headers=H("cmx"))
    assert r.status_code == 404, "已撤销候选不可再被投"


def test_annotations_csv_keeps_revoked_rows(client):
    conn = db_mod.connect()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM annotations").fetchone()["c"]
        revoked = conn.execute("SELECT COUNT(*) c FROM annotations WHERE revoked=1").fetchone()["c"]
    finally:
        conn.close()
    assert revoked > 0, "前置用例应已产生撤回留痕"
    text = client.get("/api/export/annotations.csv", headers=H("cmx")).text
    assert len(text.strip().splitlines()) - 1 == total, "留痕导出必须包含 revoked 行"


def test_voc_xml_matches_final_set(client):
    # 先把 img_01(三组分歧)以"两张空图一致"的事实多数收口成空图定稿,保证空图分支非空转
    submit(client, "cmx", "img_01", [], empty=True)
    submit(client, "hce", "img_01", [], empty=True)
    zr = client.get("/api/export/voc_xml.zip", headers=H("cmx"))
    zf = zipfile.ZipFile(io.BytesIO(zr.content))
    xmls = set(zf.namelist())
    conn = db_mod.connect()
    try:
        rows = conn.execute(
            "SELECT i.stem, a.is_empty FROM images i JOIN annotations a ON a.id=i.final_id"
            " WHERE i.final_id IS NOT NULL").fetchall()
    finally:
        conn.close()
    assert rows
    empty_seen = False
    for r in rows:
        present = (r["stem"] + ".xml") in xmls
        assert present, f"定稿图 {r['stem']} 必须在 XML 包内(含空图=负样本)"
        if r["is_empty"]:
            empty_seen = True
            assert zf.read(r["stem"] + ".xml").decode().count("<object>") == 0,                 "空图定稿的 XML 应为 0 object(负样本)"
    assert empty_seen, "本用例必须覆盖到空图定稿分支"
    voted = client.get("/api/export/labels_voted.csv", headers=H("cmx")).text
    row = [l for l in voted.splitlines() if l.startswith("img_01,")][0]
    assert ",empty," in row, "csv 侧同一张图必须标 empty —— 两种导出口径一致"


# ---------- 修复回归钉 2026-09-17(P1-1 幽灵定稿 / P1-2 兜底语义 / P1-3 悬空票) ----------

def test_resubmit_conflict_after_final_no_ghost(client):
    """P1-1 冲突路径:定稿作者改判成不同框 → 摘牌重裁,三导出同口径,无幽灵。"""
    stem = "img_02"  # 现状:票决 2:1 定稿到 cmx 的 KD(test_vote_settlement_and_tie)
    conn = db_mod.connect()
    try:
        old_final = conn.execute("SELECT final_id FROM images WHERE stem=?", (stem,)).fetchone()["final_id"]
    finally:
        conn.close()
    assert old_final, "前置:img_02 应已定稿"
    r = submit(client, "cmx", stem, [B("KD", 55, 55, 63, 63)])  # final 作者改判为远处的 KD
    assert not r.get("final_id"), "改判后进入冲突,不得沿用旧定稿"
    rv = client.get("/api/review/" + stem, headers=H("hce")).json()
    codes = sorted(c["boxes"][0]["code"] for c in rv["candidates"] if c["boxes"])
    assert not rv["final"] and len(rv["candidates"]) == 4 and codes == ["HS", "KD", "KD", "KD"],         "改判后 4 份候选(HS + 3 组 KD),不得沿用旧定稿"
    conn = db_mod.connect()
    try:
        fid = conn.execute("SELECT final_id FROM images WHERE stem=?", (stem,)).fetchone()["final_id"]
    finally:
        conn.close()
    assert fid is None, "不得残留幽灵 final_id"
    voted = client.get("/api/export/labels_voted.csv", headers=H("hce")).text
    row = [l for l in voted.splitlines() if l.startswith(stem + ",")][0]
    assert ",pending," in row, "csv 必须与库内状态一致(未定稿=pending)"
    zr = client.get("/api/export/voc_xml.zip", headers=H("hce"))
    assert (stem + ".xml") not in zr.text, "冲突图不得残留在 XML 包"


def test_resubmit_final_author_still_agree_refinal(client):
    """P1-1 一致路径:定稿作者改判但仍与他人一致 → 摘牌后自动重新定稿到有效标注。"""
    stem = "img_00"  # 现状:仅 hce 的 X 单份(final 已被 revoke 用例摘除)
    submit(client, "cmx", stem, [B("X", 12, 11, 61, 69)])  # 与 hce 现份一致 → 自动定稿
    conn = db_mod.connect()
    try:
        img = conn.execute("SELECT final_id FROM images WHERE stem=?", (stem,)).fetchone()
        hce_ann = conn.execute(
            "SELECT id FROM annotations WHERE stem=? AND annotator='hce' AND revoked=0", (stem,)).fetchone()
    finally:
        conn.close()
    assert img["final_id"] == hce_ann["id"], "一致定稿应取最早提交的 hce 份"
    r = submit(client, "hce", stem, [B("X", 13, 10, 62, 68)])  # final 作者(hce)改判,仍与 cmx 份一致
    assert r.get("final_id"), "改判后仍一致 → 自动重新定稿"
    conn = db_mod.connect()
    try:
        fid = conn.execute("SELECT final_id FROM images WHERE stem=?", (stem,)).fetchone()["final_id"]
        revoked = conn.execute("SELECT revoked FROM annotations WHERE id=?", (fid,)).fetchone()["revoked"]
    finally:
        conn.close()
    assert revoked == 0, "final 必须指向有效标注(不得是幽灵)"
    rv = client.get("/api/review/" + stem, headers=H("hce")).json()
    assert rv["final"] and all(c["annotator"] for c in rv["candidates"])


def test_tie_of_three_waits_for_4th_vote(client):
    """规则变更(2026-09-17 组长定):平票不再兜底取最早提交——保持未决;
    组内协商后改票(投票 upsert 覆盖)凑出严格过半才定稿。"""
    stem = "img_05"  # 现状:仅 cmx 的空图份
    submit(client, "hce", stem, [B("X", 5, 5, 20, 20)])
    submit(client, "zj", stem, [B("HS", 30, 30, 50, 50)])
    submit(client, "zzq", stem, [B("BX", 40, 10, 55, 25)])
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    empty_id = next(c["id"] for c in rv["candidates"] if c["is_empty"])
    x_id = next(c["id"] for c in rv["candidates"] if c["boxes"] and c["boxes"][0]["code"] == "X")
    hs_id = next(c["id"] for c in rv["candidates"] if c["boxes"] and c["boxes"][0]["code"] == "HS")
    bx_id = next(c["id"] for c in rv["candidates"] if c["boxes"] and c["boxes"][0]["code"] == "BX")
    client.post("/api/vote", json={"stem": stem, "chosen_id": empty_id}, headers=H("cmx"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": x_id}, headers=H("hce"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": hs_id}, headers=H("zj"))
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert not rv["final"], "3 票 1:1:1 → 保持未决"
    r = client.post("/api/vote", json={"stem": stem, "chosen_id": bx_id}, headers=H("zzq"))
    assert not r.json().get("final_id"), "4 票全并列 → 不再兜底,保持未决等协商"
    # 群里协商:zj 改投 X → 2:1:1 最高组唯一但不过半,仍不定稿
    client.post("/api/vote", json={"stem": stem, "chosen_id": x_id}, headers=H("zj"))
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert not rv["final"], "4 票 2:1:1 不过半 → 仍保持未决"
    # zzq 也改投 X → 3:1 严格过半 → 定稿 X 份
    r = client.post("/api/vote", json={"stem": stem, "chosen_id": x_id}, headers=H("zzq"))
    assert r.json().get("final_id") == x_id, "协商改票凑出 3/4 过半 → 定稿"


def test_dangling_votes_excluded_from_count(client):
    """P1-3:候选被撤后其选票悬空,不计入票数,也不再触发定稿/500。"""
    stem = "img_05"  # 接上:final=hce 的 X 份(协商改票定稿),第 1 轮已 4 票
    d = client.post("/api/dispute", json={"stem": stem, "reason": "四种答案差太多,重投一轮"},
                    headers=H("zzq"))
    assert d.status_code == 200 and d.json()["round"] == 2
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    x_id = next(c["id"] for c in rv["candidates"] if c["boxes"] and c["boxes"][0]["code"] == "X")
    hs_id = next(c["id"] for c in rv["candidates"] if c["boxes"] and c["boxes"][0]["code"] == "HS")
    empty_id = next(c["id"] for c in rv["candidates"] if c["is_empty"])
    client.post("/api/vote", json={"stem": stem, "chosen_id": empty_id}, headers=H("cmx"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": x_id}, headers=H("hce"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": hs_id}, headers=H("zj"))
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert not rv["final"] and rv["votes"] == 3, "第 2 轮 3 票并列,继续等"
    # cmx 撤回自己的空图份(=其选票悬空)
    r = client.post(f"/api/revoke/{empty_id}", headers=H("cmx"))
    assert r.status_code == 200
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert rv["votes"] == 2, "悬空票不计入票数"
    assert not rv["final"], "有效票不足 3 → 不得定稿,更不得 500"
    # 第三人与 hce 的 X 一致 → 事实多数收口
    submit(client, "zzq", stem, [B("X", 6, 6, 21, 21)])
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert rv["final"], "X 组 2/3 事实多数 → 定稿"


def test_comments(client):
    """图上讨论:发/读/全局流/鉴权/校验。"""
    assert client.post("/api/comments", json={"stem": "no_such", "text": "hi"},
                       headers=H("cmx")).status_code == 404
    assert client.post("/api/comments", json={"stem": "img_00", "text": "   "},
                       headers=H("cmx")).status_code == 400
    assert client.post("/api/comments", json={"stem": "img_00", "text": "这个框是不是偏了?"},
                       headers=H("cmx")).json()["ok"]
    assert client.post("/api/comments", json={"stem": "img_00", "text": "同意,重开吧"},
                       headers=H("hce")).json()["ok"]
    lst = client.get("/api/comments?stem=img_00", headers=H("hce")).json()["list"]
    assert [c["author"] for c in lst] == ["cmx", "hce"], "单图评论按时间正序"
    feed = client.get("/api/comments", headers=H("hce")).json()["list"]
    assert feed[0]["stem"] == "img_00" and feed[0]["author"] == "hce", "全局流最新在前"
    client.cookies.clear()
    assert client.get("/api/comments").status_code == 401
    assert client.post("/api/comments", json={"stem": "img_00", "text": "x"}).status_code == 401


# ---------- 弃权 + 列表分类(2026-09-16 队友需求) ----------

def test_abstain_vote(client):
    """弃权(chosen_id=-1):只留痕不计票;凑不出定稿也不阻塞他人;
    review/arbitration 可见;改投可覆盖弃权。"""
    stem = "img_06"
    submit(client, "cmx", stem, [B("HB", 10, 10, 40, 40)])
    r = submit(client, "hce", stem, [B("X", 10, 10, 40, 40)])
    assert r.get("conflict")
    # 弃权:被接受、不产生定稿
    r = client.post("/api/vote", json={"stem": stem, "chosen_id": -1}, headers=H("zj"))
    assert r.status_code == 200 and not r.json().get("final_id")
    rv = client.get("/api/review/" + stem, headers=H("zj")).json()
    assert rv["abstains"] == 1 and rv["my_vote"] == -1 and rv["votes"] == 0
    # 待决列表:zj 视角 my=-1(已表态),他人视角 my=None(待表态);involved 标记是否我标的
    arb = client.get("/api/arbitration", headers=H("zj")).json()["list"]
    o = next(x for x in arb if x["stem"] == stem)
    assert o["my"] == -1 and o["involved"] is False, "zj 没标注这张图 → involved=False"
    arb2 = client.get("/api/arbitration", headers=H("cmx")).json()["list"]
    o2 = next(x for x in arb2 if x["stem"] == stem)
    assert o2["my"] is None and o2["involved"] is True, "cmx 标过 → involved=True"
    # 弃权后补 3 实票:2:1 → 定稿(弃权不阻塞),abstains 保持留痕
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    hb = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "HB")
    for who in ("cmx", "hce", "zzq"):
        client.post("/api/vote", json={"stem": stem, "chosen_id": hb}, headers=H(who))
    rv = client.get("/api/review/" + stem, headers=H("zj")).json()
    assert rv["final"] and rv["abstains"] == 1, "3 实票定稿,弃权仅留痕"
    fin = client.get("/api/arbitration?scope=final", headers=H("zj")).json()["list"]
    o3 = next(x for x in fin if x["stem"] == stem)
    assert o3["via"] == "vote"
    assert o3["ann"] is False and o3["ann_final"] is False, "zj 没参与标注"
    assert o3["vote"] is False, "zj 只弃权,不算投过票"


def test_settle_via_unanimous_and_majority(client):
    """已定稿列表 via 分类:双标一致=unanimous;分歧后第三人补标 2/3=majority(没走投票)。"""
    submit(client, "cmx", "img_07", [B("BYW", 10, 10, 40, 40)])
    submit(client, "hce", "img_07", [B("BYW", 11, 10, 40, 40)])   # IoU 高 → 一致定稿
    fin = client.get("/api/arbitration?scope=final", headers=H("cmx")).json()["list"]
    assert next(x for x in fin if x["stem"] == "img_07")["via"] == "unanimous"
    # 一致定稿:后提交的 hce 与定稿一致 → 同样算"被采纳",不得进"我的被否"
    fin_hce = client.get("/api/arbitration?scope=final", headers=H("hce")).json()["list"]
    o7 = next(x for x in fin_hce if x["stem"] == "img_07")
    assert o7["ann"] and o7["ann_final"], "一致即采纳,不论定稿代表选了谁那份"
    # 分歧 → 第三人与 cmx 一致 → 事实多数(2/3)定稿,无投票 → majority
    submit(client, "cmx", "img_08", [B("DQK", 10, 10, 50, 50)])
    r = submit(client, "hce", "img_08", [B("XQK", 10, 10, 50, 50)])
    assert r.get("conflict")
    r = submit(client, "zj", "img_08", [B("DQK", 12, 11, 50, 50)])
    assert r.get("final_id")
    fin = client.get("/api/arbitration?scope=final", headers=H("cmx")).json()["list"]
    o = next(x for x in fin if x["stem"] == "img_08")
    assert o["via"] == "majority"
    assert o["codes"] == ["DQK"], "定稿条目应带类别(类别筛选依据)"
    assert o["ann"] and o["ann_final"], "cmx 的标注即定稿 → 我的✓"
    fin2 = client.get("/api/arbitration?scope=final", headers=H("hce")).json()["list"]
    o2 = next(x for x in fin2 if x["stem"] == "img_08")
    assert o2["ann"] and not o2["ann_final"] and not o2["vote"], "hce 被否且没投过票"


# ---------- 过程问责留痕 2026-09-18(补丁 A 改票历史 / 补丁 B 定稿事件日志) ----------

def test_vote_history_records_changed_vote(client):
    """补丁 A:同人同轮改票,旧票被 upsert 覆盖前必须先进 vote_history;同票重按不算改票。"""
    stem = "img_09"
    submit(client, "cmx", stem, [B("KD", 10, 10, 30, 30)])
    submit(client, "hce", stem, [B("HS", 40, 40, 60, 60)])
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    kd = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "KD")
    hs = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "HS")
    client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H("zzq"))
    client.post("/api/vote", json={"stem": stem, "chosen_id": hs}, headers=H("zzq"))  # 改票
    conn = db_mod.connect()
    try:
        cur = conn.execute(
            "SELECT chosen_id FROM votes WHERE stem=? AND reviewer='zzq'", (stem,)).fetchone()
        hist = conn.execute(
            "SELECT chosen_id, round FROM vote_history WHERE stem=? AND reviewer='zzq'",
            (stem,)).fetchall()
    finally:
        conn.close()
    assert cur["chosen_id"] == hs, "当前票应是改后的"
    assert len(hist) == 1 and hist[0]["chosen_id"] == kd and hist[0]["round"] == 1, \
        "被覆盖的旧票必须留史(谁、何时、投给谁)"
    client.post("/api/vote", json={"stem": stem, "chosen_id": hs}, headers=H("zzq"))  # 同票重按
    conn = db_mod.connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM vote_history WHERE stem=?",
                         (stem,)).fetchone()["c"]
    finally:
        conn.close()
    assert n == 1, "同票重复提交不算改票,不追加历史噪音"


def test_settlements_log_final_and_reopen(client):
    """补丁 B:投票定稿记 final(含票型与 via),异议重开记 reopen(含提出人与理由)。"""
    stem = "img_10"
    submit(client, "cmx", stem, [B("KD", 10, 10, 30, 30)])
    submit(client, "hce", stem, [B("HS", 40, 40, 60, 60)])
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    kd = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "KD")
    for u in ("zzq", "zj", "cmx"):
        client.post("/api/vote", json={"stem": stem, "chosen_id": kd}, headers=H(u))
    rv = client.get("/api/review/" + stem, headers=H("zzq")).json()
    assert rv["final"], "3 票 3:0 → 定稿"
    conn = db_mod.connect()
    try:
        fins = conn.execute(
            "SELECT round, final_id, tallies, note FROM settlements"
            " WHERE stem=? AND event='final'", (stem,)).fetchall()
        old_final = conn.execute("SELECT final_id FROM images WHERE stem=?",
                                 (stem,)).fetchone()["final_id"]
    finally:
        conn.close()
    assert len(fins) == 1 and fins[0]["final_id"] == old_final, "定稿事件一条,指针一致"
    assert fins[0]["note"] == "vote", "3 票定稿 via 应为 vote"
    snap = json.loads(fins[0]["tallies"])
    assert any(s.get("votes") == 3 for s in snap), "票型快照应含 3 票组"
    d = client.post("/api/dispute", json={"stem": stem, "reason": "定稿得太快,再看一眼"},
                    headers=H("zj"))
    assert d.status_code == 200
    conn = db_mod.connect()
    try:
        ro = conn.execute(
            "SELECT round, final_id, note FROM settlements WHERE stem=? AND event='reopen'",
            (stem,)).fetchall()
        now_final = conn.execute("SELECT final_id FROM images WHERE stem=?",
                                 (stem,)).fetchone()["final_id"]
    finally:
        conn.close()
    assert len(ro) == 1 and ro[0]["final_id"] == old_final and now_final is None, \
        "重开事件记录被摘掉的定稿,且指针确已清空"
    assert ro[0]["round"] == 2 and "zj" in ro[0]["note"] and "再看一眼" in ro[0]["note"], \
        "重开轮次与提出人+理由原文在案"


def test_settlements_log_unanimous_and_unseal(client):
    """补丁 B:一致定稿也留痕(via=unanimous);定稿作者改判 → unseal 摘牌留痕。"""
    stem = "img_11"
    submit(client, "cmx", stem, [B("KD", 10, 10, 30, 30)])
    r = submit(client, "hce", stem, [B("KD", 11, 10, 29, 30)])   # IoU 高 → 一致定稿
    assert r.get("final_id")
    conn = db_mod.connect()
    try:
        fins = conn.execute(
            "SELECT final_id, tallies, note FROM settlements WHERE stem=? AND event='final'",
            (stem,)).fetchall()
        old_final = conn.execute("SELECT final_id FROM images WHERE stem=?",
                                 (stem,)).fetchone()["final_id"]
    finally:
        conn.close()
    assert len(fins) == 1 and fins[0]["final_id"] == old_final and fins[0]["note"] == "unanimous"
    assert json.loads(fins[0]["tallies"])[0]["n"] == 2, "一致簇两份"
    r = submit(client, "cmx", stem, [B("KD", 50, 50, 63, 63)])   # 定稿代表(最早提交)改判到远处
    assert not r.get("final_id"), "改判后进入冲突"
    conn = db_mod.connect()
    try:
        uns = conn.execute(
            "SELECT final_id, note FROM settlements WHERE stem=? AND event='unseal'",
            (stem,)).fetchall()
    finally:
        conn.close()
    assert len(uns) == 1 and uns[0]["final_id"] == old_final and "cmx" in uns[0]["note"], \
        "摘牌事件记录被摘的定稿与行为人"


# ---------- 管理台(线下仲裁工作台)2026-09-18 ----------

def test_admin_gate_and_queue(client):
    """权限:写 admin.txt 收紧名单后,非管理员 403;队列带真名候选与重开标记。"""
    (db_mod.DATA_DIR / "admin.txt").write_text("# 只有 cmx 是管理员\ncmx\n", encoding="utf-8")
    r = client.get("/api/admin/queue", headers=H("zj"))
    assert r.status_code == 403, "非管理员必须 403"
    r = client.get("/api/admin/queue", headers=H("cmx"))
    assert r.status_code == 200
    q = {o["stem"]: o for o in r.json()["list"]}
    assert "img_11" in q and q["img_11"]["reopened"] is False, "冲突未决且无异议 → 不算重开"
    c = client.get("/api/admin/candidates?stem=img_11", headers=H("cmx")).json()
    names = {x["annotator"] for x in c["candidates"]}
    assert names == {"cmx", "hce"}, "管理台候选显示真名"
    assert client.get("/api/admin/candidates?stem=img_11", headers=H("zj")).status_code == 403
    me = client.get("/api/me", headers=H("zj")).json()
    assert me["is_admin"] is False and client.get("/api/me", headers=H("cmx")).json()["is_admin"] is True


def test_admin_finalize_skips_vote(client):
    """敲定:未满 3 票的分歧图被管理员直接定稿;settlements 记 admin 事件;via=admin。"""
    stem = "img_09"
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert not rv["final"]
    kd = next(c["id"] for c in rv["candidates"] if c["boxes"][0]["code"] == "KD")
    r = client.post("/api/admin/finalize", json={"stem": stem, "chosen_id": kd, "reason": "组长拍板"},
                    headers=H("cmx"))
    assert r.status_code == 200 and r.json()["final_id"] == kd
    rv = client.get("/api/review/" + stem, headers=H("cmx")).json()
    assert rv["final"] and rv["final_id"] == kd
    fin = client.get("/api/arbitration?scope=final", headers=H("cmx")).json()["list"]
    o = next(x for x in fin if x["stem"] == stem)
    assert o["via"] == "admin", "管理台敲定的定稿方式应为 admin"
    conn = db_mod.connect()
    try:
        row = conn.execute("SELECT note FROM settlements WHERE stem=? AND event='final'", (stem,)).fetchall()
    finally:
        conn.close()
    assert row and row[-1]["note"].startswith("admin:cmx:") and "组长拍板" in row[-1]["note"], "敲定留痕含人物与原因"


def test_admin_reopen_batch_by_code(client):
    """批量打回:只打回定稿含目标类别的图;每张 disputes+settlements 留痕;他类定稿不动。"""
    # 对照组:把 img_11 敲定为 KD 定稿(不含 BX),批量打回 BX 时必须毫发无损
    rv11 = client.get("/api/admin/candidates?stem=img_11", headers=H("cmx")).json()
    r = client.post("/api/admin/finalize", json={"stem": "img_11", "chosen_id": rv11["candidates"][0]["id"]},
                    headers=H("cmx"))
    assert r.status_code == 200
    conn = db_mod.connect()
    try:
        keep = conn.execute("SELECT final_id FROM images WHERE stem='img_11'").fetchone()["final_id"]
    finally:
        conn.close()
    assert keep, "前置:对照组 img_11 应已定稿"
    # 造一张 BX 一致定稿(img_09 当前 cmx=KD、hce=HS,补成 BX 二人一致 → 事实多数定稿)
    submit(client, "cmx", "img_09", [B("BX", 5, 5, 40, 40)])
    r = submit(client, "hce", "img_09", [B("BX", 6, 5, 41, 40)])
    assert r.get("final_id"), "BX 抱团 2/3 → 定稿"
    r = client.post("/api/admin/reopen_batch", json={"code": "BX"}, headers=H("cmx"))
    assert r.status_code == 200 and r.json()["count"] >= 1
    conn = db_mod.connect()
    try:
        s9 = conn.execute("SELECT final_id FROM images WHERE stem='img_09'").fetchone()["final_id"]
        s11 = conn.execute("SELECT final_id FROM images WHERE stem='img_11'").fetchone()["final_id"]
        d = conn.execute("SELECT raised_by, reason FROM disputes WHERE stem='img_09'"
                         " ORDER BY id DESC LIMIT 1").fetchone()
        ro = conn.execute("SELECT note FROM settlements WHERE stem='img_09' AND event='reopen'"
                          " ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert s9 is None and s11 == keep, "BX 被打回,对照组 KD 定稿不动"
    assert d and d["raised_by"] == "cmx" and d["reason"].startswith("批量打回[BX]")
    assert ro and "批量打回[BX]" in ro["note"]
    q = client.get("/api/admin/queue", headers=H("cmx")).json()["list"]
    o9 = next(x for x in q if x["stem"] == "img_09")
    assert o9["reopened"] is True, "打回后进入「本轮重开」队列"


def test_admin_claim_advisory(client):
    """占位(提示非锁):打开即认领;第二人打开收到第一人提醒;队列带占位人;非管理员 403。"""
    (db_mod.DATA_DIR / "admin.txt").write_text("cmx\nzj\n", encoding="utf-8")
    assert client.post("/api/admin/claim", json={"stem": "img_09"},
                       headers=H("hce")).status_code == 403, "非管理员不能占位"
    r = client.post("/api/admin/claim", json={"stem": "img_09"}, headers=H("cmx")).json()
    assert r["by"] is None, "第一个认领无提醒"
    r = client.post("/api/admin/claim", json={"stem": "img_09"}, headers=H("zj")).json()
    assert r["by"] == "cmx", "第二人打开应收到 cmx 刚在处理的提醒"
    q = {o["stem"]: o for o in client.get("/api/admin/queue", headers=H("cmx")).json()["list"]}
    assert q["img_09"]["claim_by"] == "zj", "队列条目带当前占位人"


def test_admin_review_list_keep_and_browse(client):
    """数据复核清单(A/B 分组+维持原判抑制)与全库回看只读清单。"""
    # A:img_00 定稿带框(X),zzq 补交空标注 → 进 A 组,建议敲定空候选
    r = submit(client, "zzq", "img_00", [], empty=True)
    rl = client.get("/api/admin/review-list", headers=H("cmx")).json()["groups"]
    a = [x for x in rl["A"] if x["stem"] == "img_00"]
    assert a and a[0]["suggest"]["empty"] is True, "A 组建议敲定空候选"
    # 维持原判 → 清单隐去
    client.post("/api/admin/review-keep", json={"stem": "img_00"}, headers=H("cmx"))
    rl = client.get("/api/admin/review-list", headers=H("cmx")).json()["groups"]
    assert not any(x["stem"] == "img_00" for x in rl["A"]), "维持后不再出现"
    # B:img_01 定稿为空,之后 hce 加框 → 进 B 组,建议敲定加框候选
    submit(client, "hce", "img_01", [B("HS", 20, 20, 80, 80)])
    rl = client.get("/api/admin/review-list", headers=H("cmx")).json()["groups"]
    b = [x for x in rl["B"] if x["stem"] == "img_01"]
    assert b and b[0]["suggest"]["by"] == "hce" and b[0]["suggest"]["nbox"] == 1
    # 回看:全部定稿图,含框明细与统计字段
    br = client.get("/api/admin/browse", headers=H("cmx")).json()["list"]
    assert len(br) >= 3
    sample = next(x for x in br if x["stem"] == "img_01")
    assert sample["empty"] is True and sample["codes"] == [] and sample["cands"] >= 2
    assert client.get("/api/admin/review-list", headers=H("hce")).status_code == 403
    assert client.get("/api/admin/browse", headers=H("hce")).status_code == 403


def test_admin_review_adjudicated_stays_closed(client):
    """复核场景收口:「都不对」→ 自己标注提交 → 敲定自己的份 → 清单收口;
    裁决之前已存在的旧分歧(别人的旧候选)不再重复触发。"""
    stem = "img_11"   # 前一组用例已管理员敲定为 cmx 的 KD(带框)
    submit(client, "zzq", stem, [B("KD", 12, 12, 40, 40)])   # 复核:自己画的版本
    rv = client.get("/api/admin/candidates?stem=" + stem, headers=H("cmx")).json()
    mine = next(c for c in rv["candidates"] if c["annotator"] == "zzq")
    client.post("/api/admin/finalize", json={"stem": stem, "chosen_id": mine["id"],
                 "reason": "复核:按我的标注定"}, headers=H("cmx"))
    rl = client.get("/api/admin/review-list", headers=H("cmx")).json()["groups"]
    assert not any(x["stem"] == stem for g in rl.values() for x in g), \
        "人工敲定即收口:裁决前的旧分歧不再触发"
    # 收口后管理台能力不变:仍可改判/维持,且依旧收口
    client.post("/api/admin/review-keep", json={"stem": stem}, headers=H("cmx"))
