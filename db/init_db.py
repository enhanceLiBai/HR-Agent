"""建表 + 插入种子数据。"""
from sqlalchemy import text
from db.database import engine


def seed_data():
    """插入种子员工和假期余额。如已存在则跳过。"""
    with engine.connect() as conn:
        # 检查是否已有数据
        result = conn.execute(text("SELECT COUNT(*) FROM employees"))
        count = result.scalar()
        if count > 0:
            print("种子数据已存在，跳过插入。")
            return

        # 插入员工
        employees = [
            {"id": "emp_001", "name": "张总",   "department": "管理部", "position": "总经理", "manager_id": None,      "hire_date": "2020-01-01"},
            {"id": "emp_002", "name": "李经理", "department": "技术部", "position": "部门总监", "manager_id": "emp_001", "hire_date": "2021-06-01"},
            {"id": "emp_003", "name": "王小明", "department": "技术部", "position": "工程师",   "manager_id": "emp_002", "hire_date": "2024-03-15"},
        ]
        for e in employees:
            conn.execute(text(
                "INSERT INTO employees (id, name, department, position, manager_id, hire_date) "
                "VALUES (:id, :name, :department, :position, :manager_id, :hire_date)"
            ), e)

        # 插入假期余额（2026年）
        leave_balances = [
            # emp_001: 张总
            {"employee_id": "emp_001", "leave_type": "annual",        "total": 5, "used": 2, "year": 2026},
            {"employee_id": "emp_001", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_001", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_001", "leave_type": "marriage",      "total": 3, "used": 0, "year": 2026},
            {"employee_id": "emp_001", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
            # emp_002: 李经理
            {"employee_id": "emp_002", "leave_type": "annual",        "total": 5, "used": 0, "year": 2026},
            {"employee_id": "emp_002", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_002", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_002", "leave_type": "marriage",      "total": 3, "used": 3, "year": 2026},
            {"employee_id": "emp_002", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
            # emp_003: 王小明
            {"employee_id": "emp_003", "leave_type": "annual",        "total": 5, "used": 5, "year": 2026},
            {"employee_id": "emp_003", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_003", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
            {"employee_id": "emp_003", "leave_type": "marriage",      "total": 3, "used": 0, "year": 2026},
            {"employee_id": "emp_003", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
        ]
        for lb in leave_balances:
            conn.execute(text(
                "INSERT INTO leave_balances (employee_id, leave_type, total, used, year) "
                "VALUES (:employee_id, :leave_type, :total, :used, :year)"
            ), lb)

        conn.commit()
        print("种子数据插入完成。")
