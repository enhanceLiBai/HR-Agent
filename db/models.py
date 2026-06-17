"""数据表模型 —— 用原生 SQL 建表，不做 ORM 映射。"""
from sqlalchemy import text
from db.database import engine


def create_tables():
    """创建所有数据表（如已存在则跳过）。"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS employees (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                department  TEXT NOT NULL,
                position    TEXT NOT NULL,
                manager_id  TEXT,
                hire_date   TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS leave_balances (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id  TEXT NOT NULL,
                leave_type   TEXT NOT NULL,
                total        REAL NOT NULL,
                used         REAL NOT NULL DEFAULT 0,
                year         INTEGER NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                UNIQUE(employee_id, leave_type, year)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS leave_requests (
                id               TEXT PRIMARY KEY,
                employee_id      TEXT NOT NULL,
                leave_type       TEXT NOT NULL,
                start_date       TEXT NOT NULL,
                end_date         TEXT NOT NULL,
                days             REAL NOT NULL,
                reason           TEXT,
                status           TEXT NOT NULL DEFAULT 'pending',
                approver_id      TEXT,
                approver_comment TEXT,
                created_at       TEXT NOT NULL,
                resolved_at      TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (approver_id) REFERENCES employees(id)
            )
        """))
        conn.commit()
