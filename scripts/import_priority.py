"""把优先重标盘点清单导入 images.priority / priority_note(2026-09-30)。

清单来源:Wafer_defect-_detection/artifacts/wafer_exp/priority_for_station.json
(scripts/wafer_exp/priority_rescan.py 六维盘点产物,格式 {stem:{tier,note}})。
幂等可重跑;库里不在清单中的图 = 普通(priority 0,不改动)。

用法:
    python scripts/import_priority.py --json path/to/priority_for_station.json \
        [--db data/labels.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="优先重标清单 → images.priority")
    ap.add_argument("--json", required=True)
    ap.add_argument("--db", default=None, help="默认用环境变量 WAFER_DB 或 ./labels.db")
    a = ap.parse_args()

    listing = json.loads(Path(a.json).read_text(encoding="utf-8"))
    db = a.db or f"{__import__('os').environ.get('WAFER_DB', 'labels.db')}"
    conn = sqlite3.connect(db)
    try:
        stems_in_db = {r[0] for r in conn.execute("SELECT stem FROM images")}
        unknown = set(listing) - stems_in_db
        if unknown:
            raise SystemExit(f"清单里有 {len(unknown)} 张不在库中(先核对数据根):"
                             f"{sorted(unknown)[:5]}")
        for stem, v in listing.items():
            conn.execute("UPDATE images SET priority=?, priority_note=? WHERE stem=?",
                         (int(v["tier"]), v.get("note", ""), stem))
        conn.commit()
        dist = Counter(r[0] for r in conn.execute(
            "SELECT priority FROM images"))
        print(f"导入 {len(listing)} 条;库内 tier 分布:{dict(sorted(dist.items(), reverse=True))}"
              f"(0=普通 1=P2抽查 2=P1核对 3=P0优先重标)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
