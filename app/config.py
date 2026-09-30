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

# 代码 → 中文名。2026-09-21 按工程师对接录音(2026-09-20)全面纠正:代码是拼音缩写——
# X=线、BX=白线、HB=黑崩、HBB=黑白崩、HBX=黑白线、XHB=小黑崩、DQK/XQK=大/小缺口、
# KD=孔洞、HS=划伤、BYW/KYW=异物。此前"黑斑系/崩边/油污"为误解,537 测试集逐类实拍
# 验证通过(证据:Wafer_defect-_detection/artifacts/wafer_exp/evidence/code_semantics_check.png)。
CODE_NAMES: dict[str, str] = {
    "X": "隐裂线", "HBB": "黑白崩", "HBX": "黑白线", "HS": "划伤", "BX": "白线",
    "KD": "孔洞", "DQK": "大缺口", "HB": "黑崩", "XQK": "小缺口", "BYW": "异物",
    "KYW": "颗粒异物", "XHB": "小黑崩",
}
# 稀有码:仅用于界面「稀有」角标。2026-09-21 起清空:BYW/KYW 旧统计"仅几框"是类名
# 误解所致(按"油污"找、按油污标),第二轮重标要按异物口径认真找,不该再打稀有标。
RARE_CODES: frozenset[str] = frozenset()

# 考卷不计分类(2026-09-29 逐类覆盖盘点,备忘录第六节):甲方新考卷(309 图)里
# HBB/BYW/XHB 真值为 0——照常标注、照常训练(练习册有真值),但考卷评分不计这三类,
# 预测单独列报。前端按钮/帮助/参照样例处都带「考卷不计」角标提醒。
EXAM_SKIP_CODES: frozenset[str] = frozenset({"HBB", "BYW", "XHB"})
# 考卷仅个位数框、无统计意义的类(带框数,文案随之)。
EXAM_THIN_CODES: dict[str, int] = {"XQK": 1}

# 尾声轻量模式(2026-09-29 用户拍板:项目尾声没时间跑双人盲标+仲裁):
# 提交即定稿、可改任何人的定稿;盲审/第三人/投票/封板不再被自动触发。
# 接口全部保留,置 False(或环境变量 WAFER_LIGHT=0)即恢复第一轮完整协作流程。
LIGHT_MODE: bool = os.environ.get("WAFER_LIGHT", "1") == "1"

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
