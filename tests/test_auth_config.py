"""轻量测试：auth.py 的 JWT_SECRET 无弱默认值（桩测试 / stub test）

验证目标：
  JWT_SECRET 未配置或为空字符串时，auth.py 必须启动即报错，且报错信息不含
  任何密钥内容；配置后 create_token / decode_token 往返正常，并且换密钥签发
  的 token 必须被拒绝（证明密钥确实参与签名）。

测试性质：
  桩测试。jose.jwt 使用最小 HMAC 桩实现，仅用于验证 create_token /
  decode_token 与 JWT_SECRET 的接线关系，**不验证真实 JWT 加密强度**
  （该部分未改动）。同时桩替换 fastapi / httpx / sqlalchemy / database。
  **不需要安装任何第三方依赖，不连接真实数据库，不发起网络请求。**

运行方式：
  python tests/test_auth_config.py

通过时退出码为 0；任一断言失败退出码为 1。
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import types
from pathlib import Path

# 项目根目录：本文件位于 <root>/tests/，向上一级即根目录。
# 使用相对解析，不依赖任何个人绝对路径，可在任意克隆位置运行。
BACKEND = Path(__file__).resolve().parent.parent / "backend-server"
sys.path.insert(0, str(BACKEND))

FAILED = []


def record(name, ok, detail=""):
    if not ok:
        FAILED.append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  — " + detail) if detail else ""))


class _StubHTTPException(Exception):
    def __init__(self, status_code=None, detail=None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _b64(x):
    return base64.urlsafe_b64encode(x).rstrip(b"=")


def _unb64(x):
    return base64.urlsafe_b64decode(x + b"=" * (-len(x) % 4))


def install_stubs():
    for k in [k for k in sys.modules if k.split(".")[0] in {"dotenv", "httpx", "fastapi", "jose", "sqlalchemy", "database"} or k == "auth"]:
        del sys.modules[k]

    d = types.ModuleType("dotenv")
    d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = d

    h = types.ModuleType("httpx")
    h.AsyncClient = object
    sys.modules["httpx"] = h

    f = types.ModuleType("fastapi")
    f.HTTPException = _StubHTTPException
    f.Depends = lambda *a, **k: None
    f.Header = lambda *a, **k: None
    sys.modules["fastapi"] = f

    class JWTError(Exception):
        pass

    def encode(payload, key, algorithm=None, **kw):
        body = dict(payload)
        exp = body.get("exp")
        body["exp"] = exp.timestamp() if hasattr(exp, "timestamp") else exp
        seg = _b64(json.dumps(body, default=str).encode())
        sig = _b64(hmac.new(str(key).encode(), seg, hashlib.sha256).digest())
        return (seg + b"." + sig).decode()

    def decode(token, key, algorithms=None, **kw):
        seg, sig = token.split(".")
        expect = _b64(hmac.new(str(key).encode(), seg.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expect, sig.encode()):
            raise JWTError("signature mismatch")
        return json.loads(_unb64(seg.encode()))

    j = types.ModuleType("jose")
    j.JWTError = JWTError
    j.jwt = types.SimpleNamespace(encode=encode, decode=decode)
    sys.modules["jose"] = j

    orm = types.ModuleType("sqlalchemy.orm")
    orm.Session = object
    sa = types.ModuleType("sqlalchemy")
    sa.orm = orm
    sys.modules["sqlalchemy"] = sa
    sys.modules["sqlalchemy.orm"] = orm

    db = types.ModuleType("database")

    class User:
        pass

    db.User = User
    db.get_db = lambda: None
    sys.modules["database"] = db


def import_auth():
    import auth
    return auth


# ── A. JWT_SECRET 未设置 -> 必须报错（证明弱默认值已移除） ────────────────
os.environ.pop("JWT_SECRET", None)
install_stubs()
try:
    import_auth()
    record("A. JWT_SECRET 未设置应报错", False, "未抛出异常 —— 弱默认值可能仍存在！")
except RuntimeError as e:
    msg = str(e)
    record("A1. JWT_SECRET 未设置应报错", True)
    record("A2. 报错信息不含任何密钥", "dev_secret" not in msg and "JWT_SECRET=" not in msg)
    record("A3. 报错给出配置指引", "JWT_SECRET" in msg)

# ── B. JWT_SECRET 为空字符串 -> 必须报错 ─────────────────────────────────
os.environ["JWT_SECRET"] = ""
install_stubs()
try:
    import_auth()
    record("B. JWT_SECRET 为空字符串应报错", False, "未抛出异常")
except RuntimeError:
    record("B. JWT_SECRET 为空字符串应报错", True)

# ── C. 配置了 JWT_SECRET -> 正常加载，且签名确实依赖该密钥 ───────────────
SECRET = "unit-test-only-secret-not-a-real-key"
os.environ["JWT_SECRET"] = SECRET
install_stubs()
try:
    auth = import_auth()
    record("C1. 配置 JWT_SECRET 后正常加载", True)
    record("C2. JWT_SECRET 取值正确", auth.JWT_SECRET == SECRET)
    record("C3. JWT_ALGORITHM 未改动", auth.JWT_ALGORITHM == "HS256")
    record("C4. JWT_EXPIRE_DAYS 未改动", auth.JWT_EXPIRE_DAYS == 30)

    tok = auth.create_token(42)
    record("C5. create_token/decode_token 往返正常", auth.decode_token(tok) == 42)

    # 用另一个密钥签发的 token 必须被拒绝 —— 证明密钥真的参与签名
    os.environ["JWT_SECRET"] = "some-other-secret"
    install_stubs()
    other = import_auth()
    forged = other.create_token(42)
    try:
        auth.decode_token(forged)
        record("C6. 换密钥签发的 token 应被拒绝", False, "伪造 token 被接受！")
    except _StubHTTPException:
        record("C6. 换密钥签发的 token 应被拒绝", True)
except Exception as e:
    record("C. 加载/往返", False, repr(e)[:90])

print()
print("结果：" + ("全部通过 ✅" if not FAILED else f"{len(FAILED)} 项失败 ❌ -> {FAILED}"))
sys.exit(1 if FAILED else 0)
