"""
auth.py — 微信登录 & JWT Token 工具
"""

import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from typing import Optional

from fastapi import Depends, HTTPException, Header
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from database import User, get_db

load_dotenv()

WECHAT_APPID     = os.getenv("WECHAT_APPID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
JWT_SECRET       = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    raise RuntimeError(
        "❌ 未检测到 JWT_SECRET，请在 .env 中配置一个足够长的随机字符串后重启服务。\n"
        '生成示例：python -c "import secrets; print(secrets.token_urlsafe(48))"'
    )
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_DAYS  = 30


# ── 微信 code 换 openid ────────────────────────────────────────────────────────
async def wx_code_to_openid(code: str) -> str:
    """调用微信接口，用 code 换取 openid"""
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid":      WECHAT_APPID,
        "secret":     WECHAT_APP_SECRET,
        "js_code":    code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=10)
        data = resp.json()

    if "errcode" in data and data["errcode"] != 0:
        raise HTTPException(status_code=401, detail=f"微信登录失败：{data.get('errmsg', '未知错误')}")
    if "openid" not in data:
        raise HTTPException(status_code=401, detail="无法获取 openid，请检查 AppID 和 AppSecret 配置")

    return data["openid"]


# ── JWT 生成 & 解析 ────────────────────────────────────────────────────────────
def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> int:
    """解析 token，返回 user_id；失败抛 HTTPException"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期，请重新登录")


# ── FastAPI 依赖：从请求头提取当前用户 ────────────────────────────────────────
def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer <token>"),
    db: Session = Depends(get_db),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供 Authorization 头，请先登录")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 格式错误，应为 Bearer <token>")
    token = authorization[7:]
    user_id = decode_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
