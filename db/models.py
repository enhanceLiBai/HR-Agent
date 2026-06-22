"""数据表模型 —— 用原生 SQL 建表，不做 ORM 映射。"""
from sqlalchemy import text
from db.database import engine


def create_tables():
    """创建所有数据表（如已存在则跳过）。"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS employees (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                department      TEXT NOT NULL,
                position        TEXT NOT NULL,
                manager_id      TEXT,
                hire_date       TEXT NOT NULL,
                feishu_open_id  TEXT,
                password_hash   TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        # 兼容旧表：如果 feishu_open_id 列不存在，添加
        try:
            conn.execute(text(
                "ALTER TABLE employees ADD COLUMN feishu_open_id TEXT"
            ))
        except Exception:
            pass  # 列已存在
        # 兼容旧表：如果 password_hash 列不存在，添加
        try:
            conn.execute(text(
                "ALTER TABLE employees ADD COLUMN password_hash TEXT"
            ))
        except Exception:
            pass  # 列已存在
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attendance_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                date        TEXT NOT NULL,
                check_in    TEXT,
                check_out   TEXT,
                status      TEXT NOT NULL DEFAULT 'normal',
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                UNIQUE(employee_id, date)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS overtime_records (
                id                   TEXT PRIMARY KEY,
                employee_id          TEXT NOT NULL,
                date                 TEXT NOT NULL,
                hours                REAL NOT NULL,
                overtime_type        TEXT NOT NULL,
                comp_hours           REAL NOT NULL,
                remaining_comp_hours REAL NOT NULL,
                expires_at           TEXT NOT NULL,
                reason               TEXT,
                status               TEXT NOT NULL DEFAULT 'pending',
                approver_id          TEXT,
                approver_comment     TEXT,
                created_at           TEXT NOT NULL,
                resolved_at          TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (approver_id) REFERENCES employees(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS feishu_sessions (
                chat_id         TEXT PRIMARY KEY,
                employee_id     TEXT NOT NULL,
                history         TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            )
        """))
        # 兼容旧表：如果 history 列不存在，添加
        try:
            conn.execute(text(
                "ALTER TABLE feishu_sessions ADD COLUMN history TEXT NOT NULL DEFAULT '[]'"
            ))
        except Exception:
            pass  # 列已存在
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS http_sessions (
                session_id   TEXT PRIMARY KEY,
                employee_id  TEXT NOT NULL,
                history      TEXT NOT NULL DEFAULT '[]',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS leave_balance_adjustments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id  TEXT NOT NULL,
                leave_type   TEXT NOT NULL,
                old_total    REAL NOT NULL,
                new_total    REAL NOT NULL,
                old_used     REAL NOT NULL,
                new_used     REAL NOT NULL,
                amount       REAL NOT NULL,
                adjusted_by  TEXT NOT NULL,
                reason       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (adjusted_by) REFERENCES employees(id)
            )
        """))
        conn.commit()
