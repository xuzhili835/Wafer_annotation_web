"""把考卷同图(stem 与考卷图 md5 相同)的甲方答案直接抄进练习册定稿(2026-09-30 用户拍板:
"反正原本也只是照着抄")。数据源 app/exam_twins.json(make 脚本生成,9 张)。

行为:每张追加一条 annotator='exam' 的候选并置为 final_id(轻量模式语义:提交即定稿);
若该图现有定稿与考卷答案完全一致则跳过(幂等,可重跑);已有 'exam' 定稿则追加覆盖。
绕过 API 直接写库=管理员操作,与 import_* 脚本同级别。

用法:
    python scripts/copy_exam_answers.py --db data/labels.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def norm(boxes: list[dict]) -> list:
    return sorted((b["code"], int(b["x0"]), int(b["y0"]), int(b["x1"]), int(b["y1"]))
                  for b in boxes)


def main() -> None:
    ap = argparse.ArgumentParser(description="考卷同图答案 → 练习册定稿")
    ap.add_argument("--db", default="data/labels.db")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    twins = json.loads((Path(__file__).resolve().parents[1] / "app" / "exam_twins.json")
                       .read_text(encoding="utf-8"))
    conn = sqlite3.connect(a.db)
    conn.row_factory = sqlite3.Row
    n_copy = n_skip_same = n_overwrite = 0
    for stem, t in sorted(twins.items()):
        img = conn.execute("SELECT stem, final_id FROM images WHERE stem=?", (stem,)).fetchone()
        if img is None:
            print(f"  跳过 {stem}:不在练习册")
            continue
        want = norm(t["boxes"])
        cur = None
        if img["final_id"]:
            f = conn.execute("SELECT annotator, boxes_json, is_empty FROM annotations WHERE id=?",
                             (img["final_id"],)).fetchone()
            if f and not f["is_empty"] and norm(json.loads(f["boxes_json"])) == want:
                n_skip_same += 1
                continue
        n_overwrite += int(img["final_id"] is not None)
        cur = conn.execute(
            "INSERT INTO annotations(stem, annotator, boxes_json, is_empty, submitted_at)"
            " VALUES(?,?,?,?,datetime('now','localtime'))",
            (stem, "exam", json.dumps(t["boxes"], ensure_ascii=False), 0))
        conn.execute("UPDATE images SET final_id=? WHERE stem=?", (cur.lastrowid, stem))
        n_copy += 1
        print(f"  抄 {stem}: {len(t['boxes'])} 框 [{t['folder']}]"
              + ("(覆盖旧定稿)" if img["final_id"] else ""))
    if not a.dry_run:
        conn.commit()
    print(f"完成:抄 {n_copy} / 已一致跳过 {n_skip_same} / 覆盖旧定稿 {n_overwrite}"
          + ("  [dry-run 未写库]" if a.dry_run else ""))


if __name__ == "__main__":
    main()
