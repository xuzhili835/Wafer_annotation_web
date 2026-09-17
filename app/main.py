"""光伏硅片缺陷标注站(FastAPI + SQLite)。

协作规则(与 docs/启动文档 一致):
- 每张图恰好预分配 2 人;不锁图,任何人可加标(接力);
- 标注只追加不改写;分歧自动进入盲审;多数票定稿,平票兜底取最早提交;
- 仲裁/审阅默认匿名(甲乙丙丁),定稿后解锁真名;
- 异议重开一轮(round+1,旧票作废);封板 3/4 同意后训练只认终版导出。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import export
from app.auth import current_user
from app.config import (ANON_NAMES, CODES, CODE_COLORS, CODE_KEYS, CODE_NAMES,
                        DATA_DIR, HOST, IOU_MATCH_THR, PORT, RARE_CODES)
from app.db import connect, init_db

app = FastAPI(title="Wafer Annotation Web", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------- 元信息 ----------------
@app.get("/health")
def health():
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM images").fetchone()["c"]
        return {"ok": True, "images": n, "time": datetime.now().isoformat(timespec="seconds")}
    finally:
        conn.close()


@app.get("/api/meta")
def meta():
    return {"codes": list(CODES), "keys": CODE_KEYS, "colors": CODE_COLORS,
            "names": CODE_NAMES, "rare": sorted(RARE_CODES)}


# ---------------- 登录 ----------------
class LoginBody(BaseModel):
    token: str


@app.post("/api/login")
def login(body: LoginBody):
    conn = connect()
    try:
        row = conn.execute("SELECT name FROM tokens WHERE token = ?", (body.token,)).fetchone()
        if not row:
            raise HTTPException(401, "令牌无效:请核对后重试")
        resp = Response(content=json.dumps({"name": row["name"]}), media_type="application/json")
        resp.set_cookie("wafer_token", body.token, max_age=7 * 24 * 3600,
                        httponly=True, samesite="lax")
        return resp
    finally:
        conn.close()


@app.post("/api/logout")
def logout():
    resp = Response(content='{"ok":true}', media_type="application/json")
    resp.delete_cookie("wafer_token")
    return resp


@app.get("/api/me")
def me(request: Request, x_token: str | None = Header(default=None)) -> dict:
    """未登录返回 {"name": null}(200),避免首访 401 刷浏览器 console error。"""
    token = x_token or request.cookies.get("wafer_token")
    if token:
        conn = connect()
        try:
            row = conn.execute("SELECT name FROM tokens WHERE token = ?", (token,)).fetchone()
        finally:
            conn.close()
        if row:
            return {"name": str(row["name"])}
    return {"name": None}


# ---------------- 框匹配与定稿引擎 ----------------
def _norm(boxes: list[dict]) -> list[tuple]:
    out = []
    for b in boxes:
        x0, x1 = sorted((int(b["x0"]), int(b["x1"])))
        y0, y1 = sorted((int(b["y0"]), int(b["y1"])))
        out.append((str(b["code"]).strip().upper(), x0, y0, x1, y1))
    return sorted(out)


def _iou(a: tuple, b: tuple) -> float:
    ix = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    iy = max(0, min(a[4], b[4]) - max(a[2], b[2]))
    inter = ix * iy
    if inter == 0:
        return 0.0
    aa = (a[3] - a[1]) * (a[4] - a[2])
    bb = (b[3] - b[1]) * (b[4] - b[2])
    return inter / max(1e-6, aa + bb - inter)


def boxes_match(a_row, b_row) -> bool:
    """两份标注是否一致:空/空一致;框数相同且同码框可按 IoU 一一配对。"""
    if a_row["is_empty"] or b_row["is_empty"]:
        return bool(a_row["is_empty"]) == bool(b_row["is_empty"])
    la = _norm(json.loads(a_row["boxes_json"]))
    lb = _norm(json.loads(b_row["boxes_json"]))
    if len(la) != len(lb):
        return False
    for code in {c for c, *_ in la}:
        ga = [b for b in la if b[0] == code]
        gb = [b for b in lb if b[0] == code]
        if len(ga) != len(gb):
            return False
        used: set[int] = set()
        for a in ga:
            best, bi = -1, -1.0
            for k, b in enumerate(gb):
                if k in used:
                    continue
                v = _iou(a, b)
                if v > bi:
                    best, bi = k, v
            if bi < IOU_MATCH_THR:
                return False
            used.add(best)
    return True


def current_round(conn, stem: str) -> int:
    """当前审阅轮次 = 异议表最大轮(无异议则 1)。旧票留在旧轮,自然作废。"""
    row = conn.execute("SELECT COALESCE(MAX(round),1) r FROM disputes WHERE stem=?",
                       (stem,)).fetchone()
    return int(row["r"])


def _candidates(conn, stem: str) -> list:
    return conn.execute(
        "SELECT * FROM annotations WHERE stem=? AND revoked=0 ORDER BY submitted_at, id",
        (stem,)).fetchall()


def try_settle(conn, stem: str) -> dict:
    """定稿引擎(幂等):候选按一致性聚类;
    - 全一致 → 自动定稿;
    - 最大组 > 半数 → 事实多数,自动定稿(取组内最早提交);
    - 否则(平票/分裂)看盲投(只数仍指向有效候选的票):≥3 票且最高组唯一 → 定稿;
      满 4 票仍并列 → 兜底取并列各组中最早提交的一份。3 票并列继续等票。"""
    img = conn.execute("SELECT final_id FROM images WHERE stem=?", (stem,)).fetchone()
    if not img:
        return {"final_id": None}
    if img["final_id"]:
        # 防幽灵定稿:final 指向的标注已被撤销/不存在时摘牌重裁
        alive = conn.execute("SELECT revoked FROM annotations WHERE id=?",
                             (img["final_id"],)).fetchone()
        if alive is None or alive["revoked"]:
            conn.execute("UPDATE images SET final_id=NULL WHERE stem=?", (stem,))
            conn.commit()
        else:
            return {"final_id": img["final_id"]}
    cands = _candidates(conn, stem)
    if len(cands) < 2:
        return {"final_id": None}
    groups: list[list] = []
    for c in cands:
        placed = False
        for g in groups:
            if boxes_match(g[0], c):
                g.append(c)
                placed = True
                break
        if not placed:
            groups.append([c])
    groups.sort(key=lambda g: (len(g), -g[0]["id"]), reverse=True)
    if len(groups) == 1:
        final_id = groups[0][0]["id"]
    elif len(groups[0]) > len(cands) / 2:
        final_id = min(m["id"] for m in groups[0])
    else:
        round_no = current_round(conn, stem)
        rows = conn.execute(
            "SELECT reviewer, chosen_id FROM votes WHERE stem=? AND round=?",
            (stem, round_no)).fetchall()
        id2group = {m["id"]: gi for gi, g in enumerate(groups) for m in g}
        votes = [v for v in rows if v["chosen_id"] in id2group]  # 悬空票(指向已撤销候选)不计
        n = len(votes)
        if n < 3:
            return {"final_id": None, "conflict": True, "votes": len(rows)}
        tally = Counter(id2group[v["chosen_id"]] for v in votes)
        top = max(tally.values())
        tops = [gi for gi, c in tally.items() if c == top]
        if len(tops) == 1 and (top > n / 2 or n >= 4):
            final_id = min(m["id"] for m in groups[tops[0]])
        elif n >= 4:
            # 兜底:并列各组中最早提交的一份(对齐启动文档口径)
            final_id = min(m["id"] for gi in tops for m in groups[gi])
        else:
            return {"final_id": None, "conflict": True, "votes": len(rows)}
    conn.execute("UPDATE images SET final_id=? WHERE stem=?", (final_id, stem))
    conn.commit()
    return {"final_id": final_id}


# ---------------- 队列与任务 ----------------
@app.get("/api/queue")
def queue(user: str = Depends(current_user)):
    """我的标注队列:①分配给我未交 ②分歧未决我没交(交叉) ③其他未定稿我没交 ④已交未定稿 ⑤已定稿(查看)。"""
    import random
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT i.stem, i.final_id, i.assignee_a, i.assignee_b FROM images i ORDER BY i.stem"
        ).fetchall()
        mine = {r["stem"]: r for r in conn.execute(
            "SELECT a.* FROM annotations a WHERE a.annotator=? AND a.revoked=0"
            " ORDER BY a.submitted_at, a.id", (user,))}
        by_stem: dict[str, list] = {}
        for r in conn.execute(
            "SELECT stem, boxes_json, is_empty, id FROM annotations WHERE revoked=0"
            " ORDER BY submitted_at, id"):
            by_stem.setdefault(r["stem"], []).append(r)
        out = []
        for r in rows:
            stem = r["stem"]
            cands = by_stem.get(stem, [])
            conflict = False
            if len(cands) >= 2:
                conflict = any(not boxes_match(cands[0], c) for c in cands[1:])
            if r["final_id"]:
                st = "final"
            elif len(cands) >= 2 and not conflict:
                st = "ready"          # 多份但一致,等引擎落 final(幂等调用即落)
            elif len(cands) >= 2:
                st = "conflict"
            elif len(cands) == 1:
                st = "wip"
            else:
                st = "pending"
            assigned = user in (r["assignee_a"], r["assignee_b"])
            submitted = stem in mine
            if st == "final":
                pri = 5
            elif submitted:
                pri = 4
            elif st == "conflict" and not submitted:
                pri = 2 if assigned else 3
            elif not submitted:
                pri = 1 if assigned else 6
            else:
                pri = 7
            if pri <= 7:
                out.append({"stem": stem, "status": st, "pri": pri, "assigned": assigned,
                            "cands": len(cands)})
        for o in out:
            if o["pri"] in (1, 2, 3):
                o["order"] = random.random()
        out.sort(key=lambda o: (o["pri"], o.get("order", o["stem"])))
        return {"queue": out}
    finally:
        conn.close()


@app.get("/api/image/{stem}")
def image(stem: str, user: str = Depends(current_user)):
    # URL 允许带 .png/.webp 后缀(前端如此拼,纯为了浏览器把响应当图片预渲染)
    stem = stem.removesuffix(".png").removesuffix(".webp")
    conn = connect()
    try:
        row = conn.execute("SELECT path FROM images WHERE stem=?", (stem,)).fetchone()
        if not row:
            raise HTTPException(404, "没有这张图")
        src = DATA_DIR / row["path"]
        # 640px 灰度原图约 400KB;转 WebP(q85)约 40KB,公网加载快一个量级。
        # 转换结果落盘复用;private 缓存:浏览器可用,CF 边缘绝不缓存(图片接口带鉴权,防穿透)
        webp = DATA_DIR / ".webp_cache" / f"{stem}.webp"
        headers = {"Cache-Control": "private, max-age=86400"}
        if webp.exists():
            return FileResponse(webp, media_type="image/webp", headers=headers)
        try:
            from PIL import Image
            webp.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                im.save(webp, "WEBP", quality=85)
            return FileResponse(webp, media_type="image/webp", headers=headers)
        except Exception:
            return FileResponse(src, media_type="image/png", headers=headers)
    finally:
        conn.close()


# ---------------- 产线参照样例(测试集,只读:不写库、不进队列) ----------------
_REF_CACHE: dict | None = None


def _ref_root():
    return DATA_DIR / "测试集"


def _ref_data() -> dict:
    """解析测试集 VOC XML → {code: [{stem, url, boxes}]}(进程内缓存)。
    每个子目录名 = 产线保证该图含该类缺陷;每类取该类框数最多的前 3 张。"""
    global _REF_CACHE
    if _REF_CACHE is not None:
        return _REF_CACHE
    import re
    import xml.etree.ElementTree as ET
    root = _ref_root()
    per_dir: dict[str, list] = {}
    if root.is_dir():
        for code_dir in sorted(root.iterdir()):
            if not code_dir.is_dir() or not re.fullmatch(r"[A-Z0-9]{1,8}", code_dir.name):
                continue
            for xf in sorted(code_dir.glob("*.xml")):
                try:
                    rt = ET.parse(xf).getroot()
                except Exception:
                    continue
                boxes = []
                for obj in rt.findall("object"):
                    name = (obj.findtext("name") or "").strip()
                    bb = obj.find("bndbox")
                    if name not in CODES or bb is None:
                        continue
                    try:
                        boxes.append({"code": name,
                                      "x0": int(float(bb.findtext("xmin", 0))),
                                      "y0": int(float(bb.findtext("ymin", 0))),
                                      "x1": int(float(bb.findtext("xmax", 0))),
                                      "y1": int(float(bb.findtext("ymax", 0)))})
                    except (TypeError, ValueError):
                        continue
                if boxes:
                    per_dir.setdefault(code_dir.name, []).append({
                        "stem": xf.stem, "dir": code_dir.name,
                        "n": sum(1 for b in boxes if b["code"] == code_dir.name),
                        "boxes": boxes})
    _REF_CACHE = {}
    for code, items in per_dir.items():
        items.sort(key=lambda r: (-r["n"], r["stem"]))
        _REF_CACHE[code] = [{"stem": r["stem"], "boxes": r["boxes"],
                             "url": f"/api/ref_image/{r['dir']}/{r['stem']}.png"}
                            for r in items[:3]]
    return _REF_CACHE


@app.get("/api/reference_prod")
def reference_prod(user: str = Depends(current_user)):
    return {"codes": _ref_data()}


@app.get("/api/ref_image/{code}/{fname}")
def ref_image(code: str, fname: str, user: str = Depends(current_user)):
    import re
    if not re.fullmatch(r"[A-Z0-9]{1,8}", code) or not re.fullmatch(r"[A-Za-z0-9._-]+", fname):
        raise HTTPException(404, "没有这张图")
    root = _ref_root()
    src = root / code / fname
    try:
        src.resolve().relative_to(root.resolve())
    except ValueError:
        raise HTTPException(404, "没有这张图")
    if not src.is_file():
        raise HTTPException(404, "没有这张图")
    webp = DATA_DIR / ".webp_cache" / f"ref_{code}_{src.stem}.webp"
    headers = {"Cache-Control": "private, max-age=86400"}
    if webp.exists():
        return FileResponse(webp, media_type="image/webp", headers=headers)
    try:
        from PIL import Image
        webp.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.save(webp, "WEBP", quality=85)
        return FileResponse(webp, media_type="image/webp", headers=headers)
    except Exception:
        return FileResponse(src, media_type="image/png", headers=headers)


@app.get("/api/task/{stem}")
def task(stem: str, user: str = Depends(current_user)):
    conn = connect()
    try:
        img = conn.execute("SELECT * FROM images WHERE stem=?", (stem,)).fetchone()
        if not img:
            raise HTTPException(404, "没有这张图")
        my = conn.execute(
            "SELECT * FROM annotations WHERE stem=? AND annotator=? AND revoked=0"
            " ORDER BY submitted_at DESC, id DESC LIMIT 1", (stem, user)).fetchone()
        draft = conn.execute(
            "SELECT boxes_json FROM drafts WHERE stem=? AND annotator=?", (stem, user)).fetchone()
        return {
            "stem": stem, "w": img["w"], "h": img["h"],
            "final": bool(img["final_id"]),
            "my_latest": dict(my) if my else None,
            "draft": json.loads(draft["boxes_json"]) if draft else None,
        }
    finally:
        conn.close()


class Box(BaseModel):
    code: str
    x0: float
    y0: float
    x1: float
    y1: float


class SubmitBody(BaseModel):
    stem: str
    boxes: list[Box] = Field(default_factory=list)
    is_empty: bool = False


def _validate(boxes: list[Box], is_empty: bool, w: int, h: int) -> list[dict]:
    if is_empty:
        return []
    if not boxes:
        raise HTTPException(400, "没有任何框:若整图无缺陷,请勾选「本图无缺陷」")
    out = []
    for b in boxes:
        code = str(b.code).strip().upper()
        if code not in CODES:
            raise HTTPException(400, f"未知缺陷代码 {code}")
        x0, x1 = sorted((max(0, min(w, int(b.x0))), max(0, min(w, int(b.x1)))))
        y0, y1 = sorted((max(0, min(h, int(b.y0))), max(0, min(h, int(b.y1)))))
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise HTTPException(400, "存在过小的框(宽或高 < 2px),请调整后再提交")
        out.append({"code": code, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return out


@app.post("/api/draft")
def save_draft(body: SubmitBody, user: str = Depends(current_user)):
    conn = connect()
    try:
        img = conn.execute("SELECT w,h FROM images WHERE stem=?", (body.stem,)).fetchone()
        if not img:
            raise HTTPException(404, "没有这张图")
        boxes = _validate(body.boxes, body.is_empty, img["w"], img["h"])
        conn.execute(
            "INSERT INTO drafts(stem,annotator,boxes_json) VALUES(?,?,?)"
            " ON CONFLICT(stem,annotator) DO UPDATE SET boxes_json=excluded.boxes_json,"
            " updated_at=datetime('now','localtime')",
            (body.stem, user, json.dumps(boxes)))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/submit")
def submit(body: SubmitBody, user: str = Depends(current_user)):
    conn = connect()
    try:
        img = conn.execute("SELECT * FROM images WHERE stem=?", (body.stem,)).fetchone()
        if not img:
            raise HTTPException(404, "没有这张图")
        boxes = _validate(body.boxes, body.is_empty, img["w"], img["h"])
        # 同人同图只保留最新一份有效标注(旧份置 revoked,留痕保留)
        old_ids = {r["id"] for r in conn.execute(
            "SELECT id FROM annotations WHERE stem=? AND annotator=? AND revoked=0",
            (body.stem, user)).fetchall()}
        conn.execute(
            "UPDATE annotations SET revoked=1 WHERE stem=? AND annotator=? AND revoked=0",
            (body.stem, user))
        if img["final_id"] and img["final_id"] in old_ids:
            # 被替换的正是当前定稿 → 摘牌,交给 try_settle 重新裁决(防幽灵定稿)
            conn.execute("UPDATE images SET final_id=NULL WHERE stem=?", (body.stem,))
        conn.execute(
            "INSERT INTO annotations(stem,annotator,boxes_json,is_empty) VALUES(?,?,?,?)",
            (body.stem, user, json.dumps(boxes), int(body.is_empty)))
        conn.execute("DELETE FROM drafts WHERE stem=? AND annotator=?", (body.stem, user))
        conn.commit()
        result = try_settle(conn, body.stem)
        return {"ok": True, **result}
    finally:
        conn.close()


@app.post("/api/revoke/{ann_id}")
def revoke(ann_id: int, user: str = Depends(current_user)):
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
        if not row or row["annotator"] != user:
            raise HTTPException(403, "只能撤销自己的标注")
        conn.execute("UPDATE annotations SET revoked=1 WHERE id=?", (ann_id,))
        conn.execute("UPDATE images SET final_id=NULL WHERE stem=? AND final_id=?",
                     (row["stem"], ann_id))
        conn.commit()
        result = try_settle(conn, row["stem"])
        return {"ok": True, **result}
    finally:
        conn.close()


# ---------------- 盲审 / 仲裁 / 异议 / 封板 ----------------
@app.get("/api/review/{stem}")
def review(stem: str, user: str = Depends(current_user)):
    conn = connect()
    try:
        img = conn.execute("SELECT * FROM images WHERE stem=?", (stem,)).fetchone()
        if not img:
            raise HTTPException(404, "没有这张图")
        cands = _candidates(conn, stem)
        revealed = bool(img["final_id"])
        anon = {c["id"]: ANON_NAMES[i] for i, c in enumerate(cands)}
        round_no = current_round(conn, stem)
        active_ids = {c["id"] for c in cands}
        all_votes = conn.execute(
            "SELECT reviewer, chosen_id FROM votes WHERE stem=? AND round=?", (stem, round_no)).fetchall()
        votes = [v for v in all_votes if v["chosen_id"] in active_ids]  # 悬空票不计入票数
        tally = Counter(v["chosen_id"] for v in votes)
        my_vote = next((v["chosen_id"] for v in votes if v["reviewer"] == user), None)
        disputes = conn.execute(
            "SELECT raised_by, reason, created_at FROM disputes WHERE stem=? ORDER BY id DESC",
            (stem,)).fetchall()
        out_cands = [{
            "id": c["id"], "anon": anon[c["id"]],
            "boxes": json.loads(c["boxes_json"]), "is_empty": bool(c["is_empty"]),
            "submitted_at": c["submitted_at"],
            "annotator": (c["annotator"] if revealed else None),
        } for c in cands]
        return {"stem": stem, "final": bool(img["final_id"]), "revealed": revealed,
                "candidates": out_cands, "tally": dict(tally), "votes": len(votes),
                "my_vote": my_vote, "round": round_no,
                "disputes": [dict(d) for d in disputes]}
    finally:
        conn.close()


class VoteBody(BaseModel):
    stem: str
    chosen_id: int


@app.post("/api/vote")
def vote(body: VoteBody, user: str = Depends(current_user)):
    conn = connect()
    try:
        c = conn.execute("SELECT id FROM annotations WHERE id=? AND stem=? AND revoked=0",
                         (body.chosen_id, body.stem)).fetchone()
        if not c:
            raise HTTPException(404, "候选不存在")
        round_no = current_round(conn, body.stem)
        conn.execute(
            "INSERT INTO votes(stem,reviewer,chosen_id,round) VALUES(?,?,?,?)"
            " ON CONFLICT(stem,reviewer,round) DO UPDATE SET chosen_id=excluded.chosen_id,"
            " voted_at=datetime('now','localtime')",
            (body.stem, user, body.chosen_id, round_no))
        conn.commit()
        result = try_settle(conn, body.stem)
        return {"ok": True, **result}
    finally:
        conn.close()


class DisputeBody(BaseModel):
    stem: str
    reason: str


@app.post("/api/dispute")
def dispute(body: DisputeBody, user: str = Depends(current_user)):
    reason = body.reason.strip()
    if len(reason) < 4:
        raise HTTPException(400, "请写一句话理由(至少 4 个字),无理由的重审不受理")
    conn = connect()
    try:
        img = conn.execute("SELECT final_id FROM images WHERE stem=?", (body.stem,)).fetchone()
        if not img:
            raise HTTPException(404, "没有这张图")
        round_no = conn.execute(
            "SELECT COALESCE(MAX(round),1) r FROM votes WHERE stem=?", (body.stem,)).fetchone()["r"]
        conn.execute("INSERT INTO disputes(stem,raised_by,reason,round) VALUES(?,?,?,?)",
                     (body.stem, user, reason, round_no + 1))
        conn.execute("UPDATE images SET final_id=NULL WHERE stem=?", (body.stem,))  # 重开(旧票原地留痕,当前轮查票自然不含)
        conn.commit()
        return {"ok": True, "round": round_no + 1}
    finally:
        conn.close()


@app.get("/api/arbitration")
def arbitration(user: str = Depends(current_user)):
    """全库待决列表:conflict(分歧未决)与有异议重开的图。"""
    conn = connect()
    try:
        rows = conn.execute("SELECT stem, final_id FROM images ORDER BY stem").fetchall()
        out = []
        for r in rows:
            if r["final_id"]:
                continue
            cands = _candidates(conn, r["stem"])
            if len(cands) >= 2 and any(not boxes_match(cands[0], c) for c in cands[1:]):
                out.append(r["stem"])
        return {"list": out}
    finally:
        conn.close()


@app.get("/api/seal")
def seal_status(user: str = Depends(current_user)):
    conn = connect()
    try:
        rows = conn.execute("SELECT voter FROM seals ORDER BY voted_at").fetchall()
        return {"votes": [r["voter"] for r in rows], "count": len(rows),
                "sealed": len(rows) >= 3}
    finally:
        conn.close()


@app.post("/api/seal")
def seal(user: str = Depends(current_user)):
    conn = connect()
    try:
        conn.execute("INSERT OR IGNORE INTO seals(voter) VALUES(?)", (user,))
        conn.commit()
        rows = conn.execute("SELECT voter FROM seals").fetchall()
        return {"ok": True, "votes": [r["voter"] for r in rows], "sealed": len(rows) >= 3}
    finally:
        conn.close()


# ---------------- 进度与导出 ----------------
@app.get("/api/progress")
def progress(user: str = Depends(current_user)):
    conn = connect()
    try:
        imgs = conn.execute("SELECT stem, final_id, assignee_a, assignee_b FROM images").fetchall()
        anns: dict[str, list] = {}
        for r in conn.execute("SELECT * FROM annotations WHERE revoked=0 ORDER BY submitted_at,id"):
            anns.setdefault(r["stem"], []).append(r)
        cells, per_person = [], {m: {"assigned": 0, "submitted": 0} for m in
                                 ("cmx", "hce", "zj", "zzq")}
        for im in imgs:
            stem = im["stem"]
            cands = anns.get(stem, [])
            conflict = len(cands) >= 2 and any(
                not boxes_match(cands[0], c) for c in cands[1:])
            if im["final_id"]:
                st = "final"
            elif conflict:
                st = "conflict"
            elif len(cands) >= 2:
                st = "ready"
            elif len(cands) == 1:
                st = "wip"
            else:
                st = "pending"
            cells.append({"stem": stem, "status": st, "n": len(cands)})
            for m in (im["assignee_a"], im["assignee_b"]):
                per_person[m]["assigned"] += 1
            submitters = {c["annotator"] for c in cands}
            for m in submitters:
                if m in per_person:
                    per_person[m]["submitted"] += 1
        return {"cells": cells, "people": per_person, "me": user}
    finally:
        conn.close()


@app.get("/api/export/annotations.csv")
def exp_annotations(user: str = Depends(current_user)):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PlainTextResponse(
        export.export_annotations_csv(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=annotations_{stamp}.csv"})


@app.get("/api/export/labels_voted.csv")
def exp_labels(user: str = Depends(current_user)):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PlainTextResponse(
        export.export_labels_voted_csv(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=labels_voted_{stamp}.csv"})


@app.get("/api/export/voc_xml.zip")
def exp_voc(user: str = Depends(current_user)):
    data, count = export.export_voc_xml_zip()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=voc_xml_{stamp}.zip",
                 "X-Final-Count": str(count)})


# ---------------- 静态前端 ----------------
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/", StaticFiles(directory="static", html=True), name="root")
