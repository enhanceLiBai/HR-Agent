"""员工信息查询工具。"""
from sqlalchemy import text
from db.database import get_session

TOOL_GET_EMPLOYEE = {
    "type": "function",
    "function": {
        "name": "get_employee",
        "description": "查询员工信息，包括部门、职位、入职日期、上级。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号"}
            },
            "required": ["employee_id"]
        }
    }
}

TOOL_GET_MY_LEAVE_HISTORY = {
    "type": "function",
    "function": {
        "name": "get_my_leave_history",
        "description": "查询员工的请假历史记录。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号"},
                "limit": {"type": "integer", "description": "返回条数，默认10"}
            },
            "required": ["employee_id"]
        }
    }
}


def get_employee(employee_id: str) -> str:
    """
    查询单个员工信息。

    参数:  employee_id - 工号
    返回:  "王小明 | 技术部 | 工程师 | 入职 2024-03-15 | 上级：李经理"
           如不存在: "未找到工号为 emp_999 的员工。"
    """
    session = get_session()
    try:
        result = session.execute(
            text("SELECT id, name, department, position, hire_date, manager_id FROM employees WHERE id = :id"),
            {"id": employee_id}
        )
        row = result.fetchone()

        if not row:
            return f"未找到工号为 {employee_id} 的员工。"

        # 查上级姓名
        manager_name = "无"
        if row.manager_id:
            mgr_result = session.execute(
                text("SELECT name FROM employees WHERE id = :id"),
                {"id": row.manager_id}
            )
            mgr_row = mgr_result.fetchone()
            if mgr_row:
                manager_name = mgr_row.name

        return f"{row.name} | {row.department} | {row.position} | 入职 {row.hire_date} | 上级：{manager_name}"
    finally:
        session.close()


def get_my_leave_history(employee_id: str, limit: int = 10) -> str:
    """
    查询员工的请假历史记录。

    参数:  employee_id - 工号
           limit        - 返回条数，默认 10

    返回:  "您的最近请假记录：
           1. [lv_a1b2c3d4] 年假 1.0天 (2026-06-18) - 已批准
           2. [lv_e5f6g7h8] 病假 2.0天 (2026-05-10至2026-05-11) - 已批准
           3. [lv_i9j0k1l2] 年假 0.5天 (2026-04-03) - 已拒绝"
    """
    session = get_session()
    try:
        result = session.execute(
            text(
                "SELECT id, leave_type, start_date, end_date, days, status "
                "FROM leave_requests "
                "WHERE employee_id = :employee_id "
                "ORDER BY created_at DESC "
                "LIMIT :limit"
            ),
            {"employee_id": employee_id, "limit": limit}
        )
        rows = result.fetchall()

        if not rows:
            return "您目前没有请假记录。"

        status_map = {"pending": "待审批", "approved": "已批准", "rejected": "已拒绝"}
        type_map = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假"
        }

        lines = ["您的最近请假记录："]
        for i, row in enumerate(rows, 1):
            leave_type_cn = type_map.get(row.leave_type, row.leave_type)
            status_cn = status_map.get(row.status, row.status)
            date_range = row.start_date if row.start_date == row.end_date else f"{row.start_date}至{row.end_date}"
            lines.append(f"{i}. [{row.id}] {leave_type_cn} {row.days}天 ({date_range}) - {status_cn}")

        return "\n".join(lines)
    finally:
        session.close()
