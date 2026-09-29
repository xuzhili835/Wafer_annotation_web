"""把第一轮定稿标注从清库前快照导入为参考层 ref_round1(只读参考,不参与判定/导出)。

用法:
    python scripts/import_round1_ref.py --snapshot backup/labels.MANUAL-SAFE-首轮.db --db data/labels.db

来源 = 快照里 images.final_id 指向的定稿标注(第一轮共识);幂等,可重复跑。
"""
from __future__ import annotations

import argparse
import json
import sqlite3


def main() -> None:
    ap = argparse.ArgumentParser(description="第一轮定稿 → ref_round1 参考层")
    ap.add_argument("--snapshot", required=True, help="清库前的 MANUAL-SAFE 快照 db")
    ap.add_argument("--db", required=True, help="线上(或本地)在用 db")
    a = ap.parse_args()

    src = sqlite3.connect(a.snapshot)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(a.db)
    dst.execute("""CREATE TABLE IF NOT EXISTS ref_round1(
        stem TEXT PRIMARY KEY, boxes_json TEXT NOT NULL, is_empty INTEGER NOT NULL,
        n_boxes INTEGER NOT NULL, final_annotator TEXT,
        imported_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")

    rows = src.execute(
        "SELECT i.stem, a.boxes_json, a.is_empty, a.annotator FROM images i"
        " JOIN annotations a ON a.id = i.final_id WHERE i.final_id IS NOT NULL"
    ).fetchall()
    n_empty = n_boxes = 0
    for r in rows:
        boxes = [] if r["is_empty"] else json.loads(r["boxes_json"])
        n_boxes += len(boxes)
        n_empty += int(bool(r["is_empty"]))
        dst.execute(
            "INSERT INTO ref_round1(stem,boxes_json,is_empty,n_boxes,final_annotator)"
            " VALUES(?,?,?,?,?) ON CONFLICT(stem) DO UPDATE SET boxes_json=excluded.boxes_json,"
            " is_empty=excluded.is_empty, n_boxes=excluded.n_boxes, final_annotator=excluded.final_annotator",
            (r["stem"], json.dumps(boxes, ensure_ascii=False), int(bool(r["is_empty"])),
             len(boxes), r["annotator"]))
    dst.commit()
    total = dst.execute("SELECT COUNT(*) FROM ref_round1").fetchone()[0]
    print(f"快照定稿 {len(rows)} 张(无缺陷 {n_empty}、共 {n_boxes} 框)→ 参考层,表内共 {total} 张")


if __name__ == "__main__":
    main()
