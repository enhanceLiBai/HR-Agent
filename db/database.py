"""SQLAlchemy 连接管理 —— 纯连接池，不做 ORM 关系映射。"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hr.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 10,  # 写锁等待 10 秒
    },
)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    """获取一个新的数据库会话。调用方负责关闭。"""
    return SessionLocal()


def init_db():
    """建表 + 插入种子数据。由 db/init_db.py 调用。"""
    from db.models import create_tables
    from db.init_db import seed_data
    create_tables()
    seed_data()
    print("数据库初始化完成。")
