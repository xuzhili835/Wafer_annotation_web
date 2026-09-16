#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wafer-label/app"
DATA_DIR="/opt/wafer-label/data"
BACKUP_DIR="/opt/wafer-label/backup"
VENV_DIR="/opt/wafer-label/venv"
SERVICE="wafer-label"
TS=$(date +%Y%m%d-%H%M%S)
LOG="/opt/wafer-label/deploy.log"

log()  { echo "[$(date '+%F %T')] $*" | tee -a "$LOG" >&2; }
fail() { log "❌ $*"; exit 2; }

mkdir -p "$BACKUP_DIR"
touch "$LOG" 2>/dev/null || { sudo touch "$LOG" && sudo chown "$USER":"$USER" "$LOG"; }

log "=============================="
log "wafer-label 部署开始"
log "=============================="

# 校验代码已由 CI 同步到位
if [ ! -f "$APP_DIR/app/main.py" ]; then
    fail "$APP_DIR/app/main.py 不存在,CI rsync 失败了?"
fi

# Step 1: 备份线上数据库(SQLite 在线备份,不断服务)
log "── Step 1: 备份数据库 ──"
DB="$DATA_DIR/labels.db"
if [ -f "$DB" ]; then
    "$VENV_DIR/bin/python" - "$DB" "$BACKUP_DIR/labels.$TS.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
sqlite3.connect(dst).backup(sqlite3.connect(src))
print("ok")
PY
    log "✓ 已备份到 $BACKUP_DIR/labels.$TS.db"
else
    log "(数据库不存在,首次部署,跳过备份)"
fi

# Step 2: 安装/更新依赖
log "── Step 2: pip 安装依赖 ──"
"$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt" \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    && log "✓ 依赖就绪" || fail "pip install 失败"

# Step 3: 重启服务
log "── Step 3: 重启 $SERVICE ──"
sudo systemctl restart "$SERVICE" || fail "systemctl restart 失败"

# Step 4: 健康检查(本机直连)
log "── Step 4: 健康检查 ──"
sleep 2
if curl -sSf -o /dev/null -m 5 "http://127.0.0.1:8100/health"; then
    log "✓ 127.0.0.1:8100/health 通过"
else
    log "⚠ 健康检查未通过!回看: sudo journalctl -u $SERVICE -n 50"
    log "  数据库备份在 $BACKUP_DIR/labels.$TS.db(本次未改动库,一般无需回滚)"
    fail "健康检查未通过"
fi

log "=============================="
log "✅ 部署完成"
log "=============================="
exit 0
