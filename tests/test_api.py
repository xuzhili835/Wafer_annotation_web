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


def _make_data(tmp_path, n=6, size=64):
    from PIL import Image
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("L", (size, size), color=i * 30 % 255).save(data / f"img_{i:02d}.png")
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
    assert len(r) == 6
    # 每张图恰好 2 个不同分配人
    conn = db_mod.connect()
    try:
        rows = conn.execute("SELECT assignee_a, assignee_b FROM images").fetchall()
        assert len(rows) == 6
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


def test_conflict_then_third_majority(client):
    submit(client, "cmx", "img_01", [B("BX", 5, 5, 40, 40)])
    r = submit(client, "hce", "img_01", [B("X", 5, 5, 40, 40)])  # 不同码 → 分歧
    assert not r.get("final_id") and r.get("conflict")
    # 第三人 zj 与 cmx 一致 → 事实多数(2/3)自动定稿
    r = submit(client, "zj", "img_01", [B("BX", 6, 6, 41, 40)])
    assert r.get("final_id")


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
        mine = conn.execute("SELECT id FROM annotations WHERE annotator='cmx' LIMIT 1").fetchone()
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


def test_validation(client):
    r = client.post("/api/submit", json={"stem": "img_04", "boxes": [], "is_empty": False},
                    headers=H("cmx"))
    assert r.status_code == 400, "有框空提交应报错引导勾选无缺陷"
    r = client.post("/api/submit", json={"stem": "img_04",
                    "boxes": [B("XX", 1, 1, 9, 9)]}, headers=H("cmx"))
    assert r.status_code == 400, "未知代码应拒绝"


# ---------- 回归校准单 2026-09-17(find-bug-skill 独立审查轮追加,全部为已验证行为的回归钉) ----------

def test_health_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_me_anonymous_returns_null_not_401(client):
    fresh = TestClient(main_mod.app)
    r = fresh.get("/api/me")
    assert r.status_code == 200 and r.json()["name"] is None, "首访 401 会刷浏览器 console error(回归:me 未登录改返 200)"


def test_logout_clears_cookie(client):
    c = TestClient(main_mod.app)
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
    for r in rows:
        present = (r["stem"] + ".xml") in xmls
        if r["is_empty"]:
            assert not present, "空图定稿不得入 XML 包"
        else:
            assert present, "非空定稿图必须在 XML 包内"
