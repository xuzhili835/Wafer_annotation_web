# Wafer_annotation_web · 光伏硅片缺陷多人标注站

给 510 张光伏硅片训练图**画框 + 每框选缺陷代码**(12 选 1,或"本图无缺陷")的四人协作标注网站。
FastAPI + SQLite(WAL)+ 原生 JS canvas,无框架无构建,2核2G 服务器友好。

> 项目背景、数据审计结论与协作机制全文见 `docs/启动文档-项目现状与标注方案.md`;
> 部署到服务器的准备工作见 `docs/服务器准备提示词.md`。

## 功能一图流

- **token 进门**:4 枚永久令牌(名字缩写前缀 + 随机串),无需注册;浏览器保存 7 天。
- **每张恰好 2 人打底**:导入图片时按人随机配对(每人约 255 张);不锁图,任何人都可加标。
- **草稿双写**:画到一半自动存草稿,刷新/崩溃不丢。
- **分歧自动进盲审**:两份标注框数相同且同码框 IoU≥0.6 视为"一致",一致即定稿;否则进入盲审,
  定稿前所有候选匿名(甲乙丙丁),任何人可投票、可一键异议(+一句话理由)重开新轮。
- **定稿规则**:全员一致 → 定稿;某一组 > 半数 → 事实多数定稿;否则票决(≥3 票且最高组唯一;
  4 票并列时取最早提交兜底)。异议重开后轮次 +1,旧票原地留痕、自然作废。
- **latest-wins**:同一人对同一张图多次提交,只算最新一份,历史自动作废但全部留痕。
- **封板 3/4**:4 人中 3 人同意即封板;导出三件套(留痕 csv / 定稿 csv / VOC XML zip)实时快照,训练只认封板终版。
- **参照样例**:从测试集挑的 12 类样例图内嵌页面(测试集只做参照,**永不参与训练**)。

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Linux/macOS: .venv/bin/pip
# 图片根目录(放 640x640 灰度 png 即可,文件主名即图片 id):
set WAFER_DATA_DIR=D:/path/to/训练集                  # Linux/macOS: export WAFER_DATA_DIR=...
.venv/Scripts/uvicorn app.main:app --port 8100
```

首次启动自动:建库 → 从 `tokens.txt` 导入令牌(无则生成 4 枚随机令牌,打印在日志里)→
扫描 `WAFER_DATA_DIR` 下全部图片并按"每张恰好 2 人"预分配。

`tokens.txt` 格式(每行 `名字:令牌`,gitignore,不进仓库):

```
cmx:cmx_xxxxxxxx
hce:hce_xxxxxxxx
zj:zj_xxxxxxxx
zzq:zzq_xxxxxxxx
```

## 测试

```bash
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest tests/ -q
```

9 个用例覆盖:登录 / 图片配对均衡 / 两份一致自动定稿 / 冲突进盲审 + 第三人事实多数 /
四份分裂票决 2:1 定稿(含匿名断言与定稿后真名解锁)/ 空图 + 异议重开 / 撤回权限 /
封板 + 三种导出 + 与测试集 VOC XML 结构对拍。

## 部署(腾讯云 2核2G + GitHub Actions)

- 推送 main 分支即自动部署:rsync 代码 → 服务器上 `deploy/deploy.sh`(SQLite 在线备份 →
  pip 装依赖 → `systemctl restart wafer-label` → 本机健康检查)→ 公网 `https://wafer.echeng.xyz/health`。
- 服务器目录:`/opt/wafer-label/{app,data,backup,venv}`;db、tokens、图片全部在 `data/`,
  `app/` 可整目录 `--delete` 同步。
- 首次准备服务器:把 `docs/服务器准备提示词.md` 全文发给服务器上的 AI;之后只需
  1) WinSCP 传图片到 `/opt/wafer-label/data`;2) 在 `data/tokens.txt` 放入正式令牌;
  3) GitHub 仓库配三个 Secrets:`SSH_PRIVATE_KEY` / `SSH_HOST` / `SSH_USER`。

## 目录结构

```
app/          FastAPI:main.py(路由)db.py(建库+配对)auth.py(token)export.py(三件套)config.py
static/       单页前端:标注画布 / 进度热力 / 审阅仲裁 / 导出 / 帮助 + 12 类参照样例(ref/)
scripts/      gen_reference.py(从测试集挑参照样例)
tests/        pytest API 冒烟
deploy/       deploy.sh(服务器侧)
docs/         启动文档、需求说明 PDF、服务器准备提示词
```

## 口径备忘

- 12 类缺陷代码的官方中文名未拿到:页面上一律"推断 + ?",拿到官方对照后只改
  `app/config.py` 的 `CODE_NAMES` 一张表。
- BYW / KYW / XHB / XQK 为稀有码:照实标,暂不参与训练(训练侧再决定忽略或合并)。
- 测试集(537 图自带产线标注)只用于评测与参照样例,永不参与任何训练。
