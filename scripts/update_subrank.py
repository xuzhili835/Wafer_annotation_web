"""给 images.sub 写级内子排序(2026-09-30):同 P0 内 考卷同图=0 → 错向=1 → 其他复检=2 → 纯稀缺=3。

依据 priority_note 关键词判档(同图优先于稀缺——同图备注常带稀缺码字样);
只动 priority>0 的图,普通图 sub 恒 0。幂等可重跑。

用法:
    python scripts/update_subrank.py --db data/labels.db
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter


def rank_of(note: str) -> int:
    if "考卷同图" in note:
        return 0
    if "错向" in note:
        return 1
    if "稀缺" in note:
        return 3
    return 2


def main() -> None:
    ap = argparse.ArgumentParser(description="写 images.sub 级内子排序")
    ap.add_argument("--db", default="data/labels.db")
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT stem, priority_note FROM images WHERE priority > 0").fetchall()
    dist: Counter[int] = Counter()
    for r in rows:
        sub = rank_of(r["priority_note"] or "")
        dist[sub] += 1
        conn.execute("UPDATE images SET sub=? WHERE stem=?", (sub, r["stem"]))
    conn.commit()
    names = {0: "考卷同图", 1: "错向", 2: "其他复检", 3: "纯稀缺"}
    total = conn.execute("SELECT COUNT(*) FROM images WHERE priority>0").fetchone()[0]
    print(f"priority>0 共 {total} 张,sub 分布: "
          + ", ".join(f"{names[k]}={v}" for k, v in sorted(dist.items())))


if __name__ == "__main__":
    main()
