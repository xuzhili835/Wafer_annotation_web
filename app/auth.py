"""token 鉴权:X-Token 头或 wafer_token cookie(图片标签走 cookie)。"""
from __future__ import annotations

import sqlite3

from fastapi import Header, HTTPException, Request

from app.db import connect


def current_user(
    request: Request,
    x_token: str | None = Header(default=None),
) -> str:
    token = x_token or request.cookies.get("wafer_token")
    if not token:
        raise HTTPException(401, "未登录:请先输入个人令牌")
    conn = connect()
    try:
        row = conn.execute("SELECT name FROM tokens WHERE token = ?", (token,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(401, "令牌无效:请核对后重新输入")
    return str(row["name"])
