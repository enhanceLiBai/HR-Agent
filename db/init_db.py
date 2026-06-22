"""建表 + 插入种子数据 + 旧数据迁移。"""
from sqlalchemy import text
from db.database import engine
from core.auth import hash_password


def _migrate_old_ids(conn):
    """将 3 位工号 (emp_001) 迁移为 4 位 (emp_0001)。
    返回是否执行了迁移。"""
    result = conn.execute(
        text("SELECT COUNT(*) FROM employees WHERE id = 'emp_001'")
    )
    if result.scalar() == 0:
        return False  # 已经是 4 位或没有旧数据

    print("检测到旧格式工号 (emp_001/2/3)，开始迁移…")
    # 关闭外键约束，避免更新时触发检查
    conn.execute(text("PRAGMA foreign_keys = OFF"))

    id_map = {
        "emp_001": "emp_0001",
        "emp_002": "emp_0002",
        "emp_003": "emp_0003",
    }
    tables_fk_columns = [
        # (表名, 列名列表)
        ("attendance_records",      ["employee_id"]),
        ("feishu_sessions",         ["employee_id"]),
        ("leave_balance_adjustments", ["employee_id", "adjusted_by"]),
        ("leave_balances",          ["employee_id"]),
        ("leave_requests",          ["employee_id", "approver_id"]),
        ("overtime_records",        ["employee_id", "approver_id"]),
    ]

    # 1️⃣ 先更新所有子表中的外键引用
    for table, columns in tables_fk_columns:
        for col in columns:
            for old_id, new_id in id_map.items():
                conn.execute(
                    text(f"UPDATE {table} SET {col} = :new WHERE {col} = :old"),
                    {"new": new_id, "old": old_id}
                )

    # 2️⃣ 更新 employees.manager_id（自引用）
    for old_id, new_id in id_map.items():
        conn.execute(
            text("UPDATE employees SET manager_id = :new WHERE manager_id = :old"),
            {"new": new_id, "old": old_id}
        )

    # 3️⃣ 最后更新 employees.id 主键
    for old_id, new_id in id_map.items():
        conn.execute(
            text("UPDATE employees SET id = :new WHERE id = :old"),
            {"new": new_id, "old": old_id}
        )

    conn.execute(text("PRAGMA foreign_keys = ON"))
    conn.commit()
    print("工号迁移完成：emp_001→emp_0001, emp_002→emp_0002, emp_003→emp_0003")
    return True


def seed_data():
    """插入种子员工和假期余额。如已存在则跳过，但会补齐缺失的密码。"""
    with engine.connect() as conn:
        # ── 先执行旧格式迁移 ──
        _migrate_old_ids(conn)

        # 检查是否已有数据
        result = conn.execute(text("SELECT COUNT(*) FROM employees"))
        count = result.scalar()
        if count > 0:
            # 已有数据 → 为没有密码的老员工设置默认密码
            default_pw = hash_password("123456")
            updated = conn.execute(
                text("UPDATE employees SET password_hash = :pw WHERE password_hash IS NULL"),
                {"pw": default_pw}
            )
            if updated.rowcount > 0:
                conn.commit()
                print(f"已为 {updated.rowcount} 个员工补齐默认密码（123456）。")
            else:
                print("种子数据已存在，跳过插入。")
            return

        # 默认密码
        default_pw = hash_password("123456")

        # 插入员工
        employees = [
            {"id": "emp_0001", "name": "张总",   "department": "管理部", "position": "总经理", "manager_id": None,       "hire_date": "2020-01-01", "password_hash": default_pw},
            {"id": "emp_0002", "name": "李经理", "department": "技术部", "position": "部门总监", "manager_id": "emp_0001", "hire_date": "2021-06-01", "password_hash": default_pw},
            {"id": "emp_0003", "name": "王小明", "department": "技术部", "position": "工程师",   "manager_id": "emp_0002", "hire_date": "2024-03-15", "password_hash": default_pw},
        ]
        for e in employees:
            conn.execute(text(
                "INSERT INTO employees (id, name, department, position, manager_id, hire_date, password_hash) "
                "VALUES (:id, :name, :department, :position, :manager_id, :hire_date, :password_hash)"
            ), e)

        # 插入假期余额（2026年）
        leave_balances = [
            # emp_0001: 张总
            {"employee_id": "emp_0001", "leave_type": "annual",        "total": 5, "used": 2, "year": 2026},
            {"employee_id": "emp_0001", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_0001", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_0001", "leave_type": "marriage",      "total": 3, "used": 0, "year": 2026},
            {"employee_id": "emp_0001", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
            # emp_0002: 李经理
            {"employee_id": "emp_0002", "leave_type": "annual",        "total": 5, "used": 0, "year": 2026},
            {"employee_id": "emp_0002", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_0002", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_0002", "leave_type": "marriage",      "total": 3, "used": 3, "year": 2026},
            {"employee_id": "emp_0002", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
            # emp_0003: 王小明
            {"employee_id": "emp_0003", "leave_type": "annual",        "total": 5, "used": 5, "year": 2026},
            {"employee_id": "emp_0003", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_0003", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_0003", "leave_type": "marriage",      "total": 3, "used": 0, "year": 2026},
            {"employee_id": "emp_0003", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
        ]
        for lb in leave_balances:
            conn.execute(text(
                "INSERT INTO leave_balances (employee_id, leave_type, total, used, year) "
                "VALUES (:employee_id, :leave_type, :total, :used, :year)"
            ), lb)

        # 插入6月考勤数据（2026年6月1日至12日，工作日）
        attendance_records = [
            # emp_001: 张总 — 全勤，偶尔早来
            {"employee_id": "emp_001", "date": "2026-06-01", "check_in": "08:45", "check_out": "18:30", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-02", "check_in": "08:50", "check_out": "19:00", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-03", "check_in": "09:20", "check_out": "18:00", "status": "late"},
            {"employee_id": "emp_001", "date": "2026-06-04", "check_in": "08:55", "check_out": "18:10", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-05", "check_in": "08:40", "check_out": "17:30", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-08", "check_in": "09:00", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-09", "check_in": "08:50", "check_out": "18:30", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-10", "check_in": "08:45", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-11", "check_in": "08:55", "check_out": "18:15", "status": "normal"},
            {"employee_id": "emp_001", "date": "2026-06-12", "check_in": "09:35", "check_out": "18:00", "status": "late"},
            # emp_002: 李经理 — 有缺勤记录
            {"employee_id": "emp_002", "date": "2026-06-01", "check_in": "08:50", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_002", "date": "2026-06-02", "check_in": "09:10", "check_out": "18:30", "status": "late"},
            {"employee_id": "emp_002", "date": "2026-06-03", "check_in": "09:00", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_002", "date": "2026-06-04", "check_in": "09:45", "check_out": "18:00", "status": "late"},
            {"employee_id": "emp_002", "date": "2026-06-05", "check_in": None,     "check_out": None,    "status": "absent"},
            {"employee_id": "emp_002", "date": "2026-06-08", "check_in": "08:55", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_002", "date": "2026-06-09", "check_in": "09:00", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_002", "date": "2026-06-10", "check_in": "09:05", "check_out": "17:00", "status": "late"},
            {"employee_id": "emp_002", "date": "2026-06-11", "check_in": "09:00", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_002", "date": "2026-06-12", "check_in": None,     "check_out": None,    "status": "absent"},
            # emp_003: 王小明 — 迟到偏多
            {"employee_id": "emp_003", "date": "2026-06-01", "check_in": "09:25", "check_out": "18:00", "status": "late"},
            {"employee_id": "emp_003", "date": "2026-06-02", "check_in": "09:15", "check_out": "18:30", "status": "late"},
            {"employee_id": "emp_003", "date": "2026-06-03", "check_in": "08:55", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_003", "date": "2026-06-04", "check_in": "09:30", "check_out": "18:00", "status": "late"},
            {"employee_id": "emp_003", "date": "2026-06-05", "check_in": "08:50", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_003", "date": "2026-06-08", "check_in": "10:00", "check_out": "18:00", "status": "late"},
            {"employee_id": "emp_003", "date": "2026-06-09", "check_in": "09:00", "check_out": "18:00", "status": "normal"},
            {"employee_id": "emp_003", "date": "2026-06-10", "check_in": "09:20", "check_out": "18:00", "status": "late"},
            {"employee_id": "emp_003", "date": "2026-06-11", "check_in": "09:10", "check_out": "17:30", "status": "late"},
            {"employee_id": "emp_003", "date": "2026-06-12", "check_in": "08:55", "check_out": "18:00", "status": "normal"},
        ]
        for a in attendance_records:
            conn.execute(text(
                "INSERT INTO attendance_records (employee_id, date, check_in, check_out, status) "
                "VALUES (:employee_id, :date, :check_in, :check_out, :status)"
            ), a)

        # 插入加班记录种子数据
        overtime_records = [
            {
                "id": "ot_a1b2c3d4",
                "employee_id": "emp_003",
                "date": "2026-06-10",
                "hours": 3.0,
                "overtime_type": "weekday",
                "comp_hours": 4.5,
                "remaining_comp_hours": 4.5,
                "expires_at": "2026-09-10",
                "reason": "项目上线前联调",
                "status": "approved",
                "approver_id": "emp_002",
                "approver_comment": "",
                "created_at": "2026-06-11 09:00:00",
                "resolved_at": "2026-06-11 10:00:00",
            },
            {
                "id": "ot_e5f6g7h8",
                "employee_id": "emp_002",
                "date": "2026-05-15",
                "hours": 4.0,
                "overtime_type": "weekend",
                "comp_hours": 8.0,
                "remaining_comp_hours": 0.0,
                "expires_at": "2026-08-15",
                "reason": "周末服务器迁移",
                "status": "approved",
                "approver_id": "emp_001",
                "approver_comment": "",
                "created_at": "2026-05-16 09:00:00",
                "resolved_at": "2026-05-16 10:00:00",
            },
        ]
        for ot in overtime_records:
            conn.execute(text(
                "INSERT INTO overtime_records (id, employee_id, date, hours, overtime_type, "
                "comp_hours, remaining_comp_hours, expires_at, reason, status, "
                "approver_id, approver_comment, created_at, resolved_at) "
                "VALUES (:id, :employee_id, :date, :hours, :overtime_type, "
                ":comp_hours, :remaining_comp_hours, :expires_at, :reason, :status, "
                ":approver_id, :approver_comment, :created_at, :resolved_at)"
            ), ot)

        # 给有调休余额的员工添加 comp 假期类型到 leave_balances
        conn.execute(text(
            "INSERT OR IGNORE INTO leave_balances (employee_id, leave_type, total, used, year) "
            "VALUES ('emp_003', 'comp', 4.5, 0, 2026)"
        ))

        conn.commit()
        print("种子数据插入完成。")
