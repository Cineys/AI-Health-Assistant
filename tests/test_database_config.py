"""轻量测试：database.py 连接串错误信息脱敏（桩测试 / stub test）

验证目标：
  未配置 DATABASE_URL 或配置了非 mysql 连接串时，database.py 抛出的异常
  不得回显完整连接串、用户名或密码，同时保留足够的排查信息（scheme）。

测试性质：
  桩测试。使用 types.ModuleType 桩替换 sqlalchemy / dotenv，再 import 真实的
  database.py。**不需要安装任何第三方依赖，不连接真实数据库，不发起网络请求。**

运行方式：
  python tests/test_database_config.py

通过时退出码为 0；任一断言失败退出码为 1。
"""
import os
import sys
import types
from pathlib import Path

# 项目根目录：本文件位于 <root>/tests/，向上一级即根目录。
# 使用相对解析，不依赖任何个人绝对路径，可在任意克隆位置运行。
BACKEND = Path(__file__).resolve().parent.parent / "backend-server"
sys.path.insert(0, str(BACKEND))


class DeclarativeBase:
    pass


class _Col:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return lambda *a, **k: self


def install_stubs():
    for m in [k for k in sys.modules if k == "database" or k.split(".")[0] in {"sqlalchemy", "dotenv"}]:
        del sys.modules[m]
    sa = types.ModuleType("sqlalchemy")
    for n in ("Boolean", "Column", "DateTime", "ForeignKey", "Index", "Integer", "String", "Text"):
        setattr(sa, n, _Col)
    sa.create_engine = lambda url, **kw: types.SimpleNamespace(url=url)
    orm = types.ModuleType("sqlalchemy.orm")
    orm.DeclarativeBase = DeclarativeBase
    orm.relationship = lambda *a, **k: None
    orm.sessionmaker = lambda **k: (lambda *a, **kk: None)
    orm.Session = object
    sa.orm = orm
    sys.modules["sqlalchemy"] = sa
    sys.modules["sqlalchemy.orm"] = orm
    d = types.ModuleType("dotenv")
    d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = d


FAILED = []


def record(name, ok, detail=""):
    if not ok:
        FAILED.append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  — " + detail) if detail else ""))


def import_fresh():
    import database
    return database


# ── A. 未配置 DATABASE_URL ────────────────────────────────────────────────
os.environ.pop("DATABASE_URL", None)
install_stubs()
try:
    import_fresh()
    record("A. 未配置 DATABASE_URL 应报错", False, "未抛出异常")
except RuntimeError as e:
    record("A. 未配置 DATABASE_URL 应报错", "DATABASE_URL" in str(e))

# ── B. 非 mysql 连接串且含密码 ────────────────────────────────────────────
FAKE_PW = "S3cr3tP@ssw0rd_FAKE"
FAKE_USER = "appuser_FAKE"
os.environ["DATABASE_URL"] = f"postgresql://{FAKE_USER}:{FAKE_PW}@127.0.0.1:5432/health_companion"
install_stubs()
try:
    import_fresh()
    record("B. 非 mysql 连接串应报错", False, "未抛出异常")
except RuntimeError as e:
    msg = str(e)
    record("B1. 异常信息不含密码", FAKE_PW not in msg, "密码泄露!" if FAKE_PW in msg else "")
    record("B2. 异常信息不含用户名", FAKE_USER not in msg, "用户名泄露!" if FAKE_USER in msg else "")
    record("B3. 异常信息不含完整 URL", "postgresql://" not in msg and "127.0.0.1" not in msg)
    record("B4. 保留排查信息（scheme）", "postgresql" in msg, msg.splitlines()[0][:70])
    record("B5. 仍提示正确格式", "mysql+pymysql" in msg)

# ── C. 无 "://" 的畸形值不得回显原值 ──────────────────────────────────────
os.environ["DATABASE_URL"] = "this_is_not_a_url_FAKEMARKER"
install_stubs()
try:
    import_fresh()
    record("C. 畸形连接串应报错", False, "未抛出异常")
except RuntimeError as e:
    record("C1. 畸形值不回显原值", "FAKEMARKER" not in str(e))
    record("C2. 给出兜底提示", "无法识别" in str(e))

# ── D. 正常 mysql 连接串应放行（回归） ────────────────────────────────────
os.environ["DATABASE_URL"] = "mysql+pymysql://u:p@127.0.0.1:3306/health_companion?charset=utf8mb4"
install_stubs()
try:
    import_fresh()
    record("D. 正常 mysql 连接串应通过（回归）", True)
except Exception as e:
    record("D. 正常 mysql 连接串应通过（回归）", False, repr(e)[:90])

# ── E. 表结构未被改动（回归） ─────────────────────────────────────────────
os.environ["DATABASE_URL"] = "mysql+pymysql://u:p@127.0.0.1:3306/db"
install_stubs()
mod = import_fresh()
expected = {"User", "MoodRecord", "ChatSession", "ChatMessage", "Report", "Medication", "MedicationCheckin"}
got = {n for n in expected if hasattr(mod, n)}
record("E1. 7 个 ORM 模型齐全", got == expected, f"缺失: {expected - got}" if got != expected else "")
record("E2. init_db / get_db 存在", hasattr(mod, "init_db") and hasattr(mod, "get_db"))

print()
print("结果：" + ("全部通过 ✅" if not FAILED else f"{len(FAILED)} 项失败 ❌ -> {FAILED}"))
sys.exit(1 if FAILED else 0)
