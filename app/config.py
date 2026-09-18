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

# 代码 → 中文名。2026-09-17 由队友逐类看实际图像 + 产线目录名交叉确认
# (X 的标注路径就叫「隐裂」、BX 路径含「白色崩边」、KD 路径直接叫「孔洞」),原推断+问号表作废;
# 若数据方后续给出官方对照且有出入,以官方为准,只改这张表。
CODE_NAMES: dict[str, str] = {
    "X": "隐裂", "HBB": "黑斑-边部", "HBX": "黑斑-心部", "HS": "划伤", "BX": "崩边",
    "KD": "孔洞", "DQK": "大缺角", "HB": "黑斑", "XQK": "小缺角", "BYW": "油污",
    "KYW": "颗粒油污", "XHB": "线黑斑",
}
# 稀有码:仅用于界面「稀有」角标,系统不丢弃任何标注;是否参与训练由训练侧按最终分布决定。
# 2026-09-17 实测训练标注 167 框:XQK 占 23%(40 框)为最高频、XHB 占 9%,均移出稀有
# (抽图与产线参照比对,形态一致,非误标);BYW 2% / KYW 0.6% 保持稀有。
RARE_CODES: frozenset[str] = frozenset({"BYW", "KYW"})

MEMBERS = ("cmx", "hce", "zj", "zzq")
ANON_NAMES = ("甲", "乙", "丙", "丁")  # 盲审匿名代称(按候选提交先后固定映射)

IOU_MATCH_THR = 0.6          # 两框视为"同一处"的 IoU 阈值
REVIEW_ROUND = 1             # dispute 每开一轮 +1,旧票作废


def load_admins() -> set[str]:
    """管理员名单:DATA_DIR/admin.txt 一行一个名字(# 开头为注释),实时读取、改完即生效;
    文件不存在或为空 = 全员管理员(线下仲裁不固定谁操作,哪台电脑登谁 token 都行)。"""
    f = DATA_DIR / "admin.txt"
    if f.exists():
        names = {ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")}
        return names or set(MEMBERS)
    return set(MEMBERS)
