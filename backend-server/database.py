"""
database.py — SQLAlchemy 数据库配置与 ORM 模型（MySQL）
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Index, Integer, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

load_dotenv()

# ── 连接字符串 ─────────────────────────────────────────────────────────────────
# 在 .env 中配置：
#   DATABASE_URL=mysql+pymysql://user:password@host:3306/health_companion?charset=utf8mb4
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "❌ 未检测到 DATABASE_URL，请在 .env 中配置 MySQL 连接字符串。\n"
        "示例：DATABASE_URL=mysql+pymysql://appuser:password@127.0.0.1:3306/health_companion?charset=utf8mb4"
    )
if not DATABASE_URL.startswith("mysql"):
    # 只回显 scheme，避免把账号密码写进异常信息
    _scheme = DATABASE_URL.split("://", 1)[0] if "://" in DATABASE_URL else "无法识别"
    raise RuntimeError(
        f"❌ DATABASE_URL 不是 MySQL 连接字符串（检测到的 scheme：{_scheme}）。\n"
        "请使用 mysql+pymysql:// 格式。"
    )

# ── 引擎配置 ──────────────────────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    pool_size=10,       # 连接池常驻连接数
    max_overflow=20,    # 峰值时可额外借出，总计最多 30
    pool_pre_ping=True, # 取连接前先 ping，自动清除断开的僵尸连接
    pool_recycle=1800,  # 30 分钟回收一次，防止 MySQL 8h wait_timeout 断连
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ── 用户表 ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    openid     = Column(String(64), unique=True, index=True, nullable=False)
    nickname   = Column(String(64), default="健康用户")
    created_at = Column(DateTime, default=datetime.utcnow)

    mood_records  = relationship("MoodRecord",        back_populates="user", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession",       back_populates="user", cascade="all, delete-orphan")
    reports       = relationship("Report",            back_populates="user", cascade="all, delete-orphan")
    medications   = relationship("Medication",        back_populates="user", cascade="all, delete-orphan")
    med_checkins  = relationship("MedicationCheckin", back_populates="user", cascade="all, delete-orphan")


# ── 心情打卡表 ─────────────────────────────────────────────────────────────────
class MoodRecord(Base):
    __tablename__ = "mood_records"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    date_key   = Column(String(10), nullable=False)   # "YYYY-MM-DD"
    mood_index = Column(Integer,   nullable=False)    # 0~4
    emoji      = Column(String(8), nullable=False)
    label      = Column(String(16), nullable=False)
    diary_text = Column(Text, default="")             # MySQL TEXT，最大 65 KB
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="mood_records")


# ── 对话会话表 ─────────────────────────────────────────────────────────────────
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    mode       = Column(String(16), default="medical")   # medical | emotional | diet
    created_at = Column(DateTime, default=datetime.utcnow)

    user     = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.id")
    reports  = relationship("Report", back_populates="session")


# ── 对话消息表 ─────────────────────────────────────────────────────────────────
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role       = Column(String(8), nullable=False)    # user | ai
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


# ── 报告表 ─────────────────────────────────────────────────────────────────────
class Report(Base):
    __tablename__ = "reports"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id      = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    chief_complaint = Column(Text, default="")
    symptoms        = Column(Text, default="")
    accompanying    = Column(Text, default="")
    relief_tried    = Column(Text, default="")
    ai_assessment   = Column(Text, default="")
    recommendation  = Column(Text, default="")
    disclaimer      = Column(Text, default="")
    # JSON 报告可能较长，使用 MEDIUMTEXT（最大 16 MB）
    raw_text        = Column(Text().with_variant(Text(16777215), "mysql"), default="")
    # ── v2.0 新增字段 ──────────────────────────────────────────────────────────
    doctor_report   = Column(Text, nullable=True)             # 面向医生的专业术语版内容
    report_type     = Column(String(16), default="standard") # standard | monthly
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)

    user    = relationship("User",        back_populates="reports")
    session = relationship("ChatSession", back_populates="reports")


# ── 用药记录表 ─────────────────────────────────────────────────────────────────
class Medication(Base):
    __tablename__ = "medications"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    name       = Column(String(64),  nullable=False)
    dosage     = Column(String(32),  default="")
    times      = Column(String(128), nullable=False)   # JSON 字符串，如 '["morning","evening"]'
    note       = Column(String(128), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user     = relationship("User",               back_populates="medications")
    checkins = relationship("MedicationCheckin",  back_populates="medication",
                            cascade="all, delete-orphan")


# ── 服药打卡表 ─────────────────────────────────────────────────────────────────
class MedicationCheckin(Base):
    __tablename__ = "medication_checkins"

    id        = Column(Integer, primary_key=True, index=True)
    user_id   = Column(Integer, ForeignKey("users.id"),    nullable=False)
    med_id    = Column(Integer, ForeignKey("medications.id"), nullable=False)
    date_key  = Column(String(10), nullable=False)    # "YYYY-MM-DD"
    time_slot = Column(String(16), nullable=False)    # morning | noon | evening | bedtime

    medication = relationship("Medication", back_populates="checkins")
    user       = relationship("User",       back_populates="med_checkins")

    __table_args__ = (
        Index("ix_med_checkin_user_date", "user_id", "date_key"),
    )


# ── 初始化所有表 ───────────────────────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)


# ── FastAPI 依赖注入用的 Session 生成器 ───────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
