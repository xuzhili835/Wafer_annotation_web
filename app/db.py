"""SQLite 建表与连接(WAL)。并发极低(4 人),每请求短连接即可。"""
from __future__ import annotations

import sqlite3

from app.config import DB_PATH, DATA_DIR, TOKENS_FILE, MEMBERS, IMG_EXTS
import secrets

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens(
  name TEXT PRIMARY KEY,
  token TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS images(
  stem TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  w INTEGER NOT NULL,
  h INTEGER NOT NULL,
  assignee_a TEXT NOT NULL,
  assignee_b TEXT NOT NULL,
  final_id INTEGER                -- 定稿 annotation id,NULL=未定稿
);
CREATE TABLE IF NOT EXISTS annotations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stem TEXT NOT NULL,
  annotator TEXT NOT NULL,
  boxes_json TEXT NOT NULL,       -- [{code,x0,y0,x1,y1}]
  is_empty INTEGER NOT NULL DEFAULT 0,
  submitted_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drafts(
  stem TEXT NOT NULL,
  annotator TEXT NOT NULL,
  boxes_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  PRIMARY KEY(stem, annotator)
);
CREATE TABLE IF NOT EXISTS votes(
  stem TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  chosen_id INTEGER NOT NULL,
  round INTEGER NOT NULL DEFAULT 1,
  voted_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  PRIMARY KEY(stem, reviewer, round)
);
CREATE TABLE IF NOT EXISTS disputes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stem TEXT NOT NULL,
  raised_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  round INTEGER NOT NULL,          -- 触发的重审轮次
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS seals(
  voter TEXT PRIMARY KEY,
  voted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _ensure_tokens(conn)
        _ensure_images(conn)
    finally:
        conn.close()


def _ensure_tokens(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()
    if row["c"]:
        return
    # 首次:tokens.txt 有则导入(name:token),否则自动生成并落盘
    entries: list[tuple[str, str]] = []
    if TOKENS_FILE.exists():
        for line in TOKENS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and ":" in line and not line.startswith("#"):
                name, tok = line.split(":", 1)
                entries.append((name.strip(), tok.strip()))
    if not entries:
        for name in MEMBERS:
            entries.append((name, f"{name}_{secrets.token_urlsafe(6)}"))
        TOKENS_FILE.write_text(
            "# name:token —— 每人一枚,永久有效;泄露时可只改对应行后重启\n"
            + "\n".join(f"{n}:{t}" for n, t in entries) + "\n",
            encoding="utf-8",
        )
    conn.executemany("INSERT OR IGNORE INTO tokens(name, token) VALUES(?,?)", entries)
    conn.commit()


def _ensure_images(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) c FROM images").fetchone()
    if row["c"]:
        return
    if not DATA_DIR.exists():
        return
    files = sorted(p for p in DATA_DIR.rglob("*") if p.suffix.lower() in IMG_EXTS)
    if not files:
        return
    from PIL import Image
    import random

    stems = [p.stem for p in files]
    random.shuffle(stems)
    n = len(MEMBERS)
    per = -(-len(stems) * 2 // n)          # 每人槽位 = ceil(2*张数/人数)
    slots = [m for m in MEMBERS for _ in range(per)]
    # 每张取两个不同的人:按"剩余槽位最多者优先"两两配对(堆),
    # 数学上保证一对内两人必不同,且每人槽位数与预分配严格一致
    import heapq
    from collections import Counter
    heap = [(-v, m) for m, v in Counter(slots).items()]
    heapq.heapify(heap)
    pairs: list[tuple[str, str]] = []
    for _ in range(len(stems)):
        first = heapq.heappop(heap)
        second = heapq.heappop(heap)
        pairs.append((first[1], second[1]))
        if first[0] + 1 < 0:
            heapq.heappush(heap, (first[0] + 1, first[1]))
        if second[0] + 1 < 0:
            heapq.heappush(heap, (second[0] + 1, second[1]))
    random.shuffle(pairs)
    pairs = [(a, b) if random.random() < 0.5 else (b, a) for a, b in pairs]
    rows = []
    for p, (a, b) in zip(files, pairs):
        with Image.open(p) as im:
            w, h = im.size
        rel = p.relative_to(DATA_DIR).as_posix()
        rows.append((p.stem, rel, w, h, a, b))
    conn.executemany(
        "INSERT OR IGNORE INTO images(stem,path,w,h,assignee_a,assignee_b,final_id)"
        " VALUES(?,?,?,?,?,?,NULL)",
        rows,
    )
    conn.commit()
