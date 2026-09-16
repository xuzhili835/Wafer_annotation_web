"""路径与服务配置。环境变量可覆盖,便于服务器部署(/opt/wafer-label)。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("WAFER_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("WAFER_DB", BASE_DIR / "labels.db"))
TOKENS_FILE = Path(os.environ.get("WAFER_TOKENS", BASE_DIR / "tokens.txt"))

HOST = os.environ.get("WAFER_HOST", "127.0.0.1")
PORT = int(os.environ.get("WAFER_PORT", "8100"))

IMG_EXTS = {".png", ".jpg", ".jpeg"}
IMG_SIZE_DEFAULT = (640, 640)

# 12 类缺陷代码:顺序即快捷键与按钮顺序;颜色为画布框色(高对比)
CODES: tuple[str, ...] = (
    "X", "HBB", "HBX", "HS", "BX", "KD", "DQK", "HB", "XQK", "BYW", "KYW", "XHB",
)
# 快捷键:1-9、0、Q、W 依 CODES 顺序;"本图无缺陷"= N
CODE_KEYS: dict[str, str] = {c: k for c, k in zip(CODES, ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "Q", "W"))}
CODE_COLORS: dict[str, str] = {c: v for c, v in zip(CODES, (
    "#f43f5e", "#f59e0b", "#22c55e", "#06b6d4", "#3b82f6", "#a855f7",
    "#eab308", "#ec4899", "#14b8a6", "#8b5cf6", "#84cc16", "#fb7185",
))}

# 代码 → 中文推断(全部带问号;官方对照拿到后只改这张表与前端展示)
CODE_NAMES: dict[str, str] = {
    "X": "线痕?", "HBB": "黑斑类??", "HBX": "复合缺陷?", "HS": "隐裂?", "BX": "崩边?",
    "KD": "孔洞?", "DQK": "待定", "HB": "黑斑?", "XQK": "待定", "BYW": "边缘污?",
    "KYW": "待定", "XHB": "待定(仅1例)",
}
# 稀有码:照实标,暂不参与训练(训练侧再决定忽略/合并)
RARE_CODES: frozenset[str] = frozenset({"BYW", "KYW", "XHB", "XQK"})

MEMBERS = ("cmx", "hce", "zj", "zzq")
ANON_NAMES = ("甲", "乙", "丙", "丁")  # 盲审匿名代称(按候选提交先后固定映射)

IOU_MATCH_THR = 0.6          # 两框视为"同一处"的 IoU 阈值
REVIEW_ROUND = 1             # dispute 每开一轮 +1,旧票作废
