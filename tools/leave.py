"""请假相关工具函数。"""
import secrets
from datetime import datetime
from sqlalchemy import text
from db.database import get_session

TOOL_QUERY_LEAVE_BALANCE = {
    "type": "function",
    "function": {
        "name": "query_leave_balance",
        "description": "查询员工的某种假期余额。在提交请假申请前必须调用，确认员工有足够余额。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号，如 emp_001"},
                "leave_type": {
                    "type": "string",
                    "enum": ["annual", "personal", "sick", "marriage", "bereavement", "maternity", "paternity"],
                    "description": "假期类型"
                }
            },
            "required": ["employee_id", "leave_type"]
        }
    }
}

TOOL_CREATE_LEAVE_REQUEST = {
    "type": "function",
    "function": {
        "name": "create_leave_request",
        "description": "创建请假申请。只有在制度合规、余额充足的前提下才调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "申请人工号"},
                "leave_type": {"type": "string", "description": "假期类型"},
                "start_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD，单天与 start_date 相同"},
                "reason": {"type": "string", "description": "请假原因"}
            },
            "required": ["employee_id", "leave_type", "start_date", "end_date", "reason"]
        }
    }
}

TOOL_APPROVE_LEAVE = {
    "type": "function",
    "function": {
        "name": "approve_leave",
        "description": "审批通过一条请假申请。仅管理者使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "申请编号"},
                "approver_id": {"type": "string", "description": "审批人工号"},
                "comment": {"type": "string", "description": "审批意见（可选）"}
            },
            "required": ["request_id", "approver_id"]
        }
    }
}

TOOL_REJECT_LEAVE = {
    "type": "function",
    "function": {
        "name": "reject_leave",
        "description": "拒绝一条请假申请。仅管理者使用。需填写拒绝原因。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "申请编号"},
                "approver_id": {"type": "string", "description": "审批人工号"},
                "reason": {"type": "string", "description": "拒绝原因"}
            },
            "required": ["request_id", "approver_id", "reason"]
        }
    }
}

TOOL_LIST_PENDING_APPROVALS = {
    "type": "function",
    "function": {
        "name": "list_pending_approvals",
        "description": "列出等待某管理者审批的所有请假申请。",
        "parameters": {
            "type": "object",
            "properties": {
                "manager_id": {"type": "string", "description": "管理者的工号"}
            },
            "required": ["manager_id"]
        }
    }
}


def query_leave_balance(employee_id: str, leave_type: str) -> str:
    """
    查询指定员工的某种假期余额。

    参数:  employee_id - 员工工号
           leave_type   - 假期类型

    返回:  "年假：总额5.0天，已用2.0天，剩余3.0天"
           如果无记录: "未找到 emp_001 的 annual 假期记录"
           如果余额为0: "年假：总额5.0天，已用5.0天，剩余0.0天（已用完）"
    """
    valid_types = ["annual", "personal", "sick", "marriage", "bereavement", "maternity", "paternity"]
    if leave_type not in valid_types:
        return f"❌ 无效的假期类型: {leave_type}。有效类型: {', '.join(valid_types)}"

    type_names = {
        "annual": "年假", "personal": "事假", "sick": "病假",
        "marriage": "婚假", "bereavement": "丧假",
        "maternity": "产假", "paternity": "陪产假"
    }

    session = get_session()
    try:
        result = session.execute(
            text(
                "SELECT total, used FROM leave_balances "
                "WHERE employee_id = :employee_id AND leave_type = :leave_type AND year = 2026"
            ),
            {"employee_id": employee_id, "leave_type": leave_type}
        )
        row = result.fetchone()

        if not row:
            return f"未找到 {employee_id} 的 {leave_type} 假期记录。"

        total = row.total
        used = row.used
        remaining = total - used
        name_cn = type_names.get(leave_type, leave_type)

        if remaining <= 0:
            return f"{name_cn}：总额{total}天，已用{used}天，剩余{remaining}天（已用完）"

        return f"{name_cn}：总额{total}天，已用{used}天，剩余{remaining}天"
    finally:
        session.close()


def create_leave_request(
    employee_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str
) -> str:
    """
    创建一条请假申请，状态为 pending。

    参数:  employee_id - 申请人工号
           leave_type   - 假期类型
           start_date   - 开始日期 "YYYY-MM-DD"
           end_date     - 结束日期 "YYYY-MM-DD"（单天则等于 start_date）
           reason       - 请假原因

    返回:  "✅ 请假申请已提交（编号 lv_a1b2c3d4）
           类型：年假  日期：2026-06-18 至 2026-06-18  天数：1.0天
           状态：等待 李经理 审批"

    注意:  此函数不做合规检查，合规检查由 Agent 在调用前完成。
    """
    session = get_session()
    try:
        # 1. 生成唯一 ID
        request_id = "lv_" + secrets.token_hex(4)

        # 2. 计算天数
        from datetime import date
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        days = (e - s).days + 1.0

        # 年假支持半天：单天 + reason 中提到"半天" → 0.5
        if leave_type == "annual" and start_date == end_date and "半天" in reason:
            days = 0.5

        # 3. 获取默认审批人
        approver_id = None
        approver_name = "上级"
        emp_result = session.execute(
            text("SELECT manager_id, name FROM employees WHERE id = :id"),
            {"id": employee_id}
        )
        emp_row = emp_result.fetchone()
        if emp_row:
            if emp_row.manager_id:
                approver_id = emp_row.manager_id
                mgr_result = session.execute(
                    text("SELECT name FROM employees WHERE id = :id"),
                    {"id": emp_row.manager_id}
                )
                mgr_row = mgr_result.fetchone()
                if mgr_row:
                    approver_name = mgr_row.name
            else:
                # 无上级（总经理）→ 自动通过
                approver_name = "无（自动通过）"

        # 4. 插入记录
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假"
        }
        type_cn = type_names.get(leave_type, leave_type)

        session.execute(
            text(
                "INSERT INTO leave_requests (id, employee_id, leave_type, start_date, end_date, days, reason, status, approver_id, created_at) "
                "VALUES (:id, :employee_id, :leave_type, :start_date, :end_date, :days, :reason, 'pending', :approver_id, :created_at)"
            ),
            {
                "id": request_id,
                "employee_id": employee_id,
                "leave_type": leave_type,
                "start_date": start_date,
                "end_date": end_date,
                "days": days,
                "reason": reason,
                "approver_id": approver_id,
                "created_at": created_at,
            }
        )
        session.commit()

        # 5. 如果无上级（总经理），自动通过
        if not approver_id:
            approve_leave(request_id, employee_id, "无上级，自动通过")

            # 重新获取状态
            result = session.execute(
                text("SELECT status FROM leave_requests WHERE id = :id"),
                {"id": request_id}
            )
            new_status = result.fetchone().status
            status_cn = "已批准" if new_status == "approved" else new_status
            return (
                f"✅ 请假申请已提交（编号 {request_id}）\n"
                f"类型：{type_cn}  日期：{start_date} 至 {end_date}  天数：{days}天\n"
                f"状态：{status_cn}（总经理无需审批，自动通过）"
            )

        return (
            f"✅ 请假申请已提交（编号 {request_id}）\n"
            f"类型：{type_cn}  日期：{start_date} 至 {end_date}  天数：{days}天\n"
            f"状态：等待 {approver_name} 审批"
        )
    finally:
        session.close()


def approve_leave(request_id: str, approver_id: str, comment: str = "") -> str:
    """
    审批通过一条请假申请。

    参数:  request_id   - 申请编号
           approver_id  - 审批人工号
           comment      - 审批意见（可选）

    返回:  "✅ 已批准 lv_a1b2c3d4（年假 1.0天），已扣除年假余额。"
           或 "❌ 该申请已被处理，无法重复审批。"
           或 "❌ 权限不足：该申请需上级审批。"
    """
    session = get_session()
    try:
        # 1. 查找申请
        result = session.execute(
            text("SELECT * FROM leave_requests WHERE id = :id"),
            {"id": request_id}
        )
        row = result.fetchone()
        if not row:
            return f"❌ 未找到编号为 {request_id} 的请假申请。"

        # 2. 校验状态
        if row.status != "pending":
            return f"❌ 该申请已被处理，无法重复审批。"

        # 3. 校验权限：审批人必须是记录的 approver_id，或者是无上级的特殊情况
        if row.approver_id and row.approver_id != approver_id:
            # 检查审批人是否是申请人的上上级（自动转给上上级）
            emp_result = session.execute(
                text("SELECT manager_id FROM employees WHERE id = :id"),
                {"id": row.employee_id}
            )
            emp_row = emp_result.fetchone()
            if emp_row and emp_row.manager_id == approver_id:
                # 审批人是直属上级
                pass
            else:
                return f"❌ 权限不足：该申请需上级审批。"

        # 4. 更新状态
        resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.execute(
            text(
                "UPDATE leave_requests SET status='approved', approver_id=:approver_id, "
                "approver_comment=:comment, resolved_at=:resolved_at WHERE id=:id"
            ),
            {
                "approver_id": approver_id,
                "comment": comment if comment else "",
                "resolved_at": resolved_at,
                "id": request_id,
            }
        )

        # 5. 带薪假期扣减额度
        paid_types = ["annual", "marriage", "bereavement", "maternity", "paternity"]
        if row.leave_type in paid_types:
            session.execute(
                text(
                    "UPDATE leave_balances SET used = used + :days "
                    "WHERE employee_id = :employee_id AND leave_type = :leave_type AND year = 2026"
                ),
                {
                    "days": row.days,
                    "employee_id": row.employee_id,
                    "leave_type": row.leave_type,
                }
            )

        session.commit()

        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假"
        }
        type_cn = type_names.get(row.leave_type, row.leave_type)

        if row.leave_type in paid_types:
            return f"✅ 已批准 {request_id}（{type_cn} {row.days}天），已扣除{type_cn}余额。"
        else:
            return f"✅ 已批准 {request_id}（{type_cn} {row.days}天）。"
    finally:
        session.close()


def reject_leave(request_id: str, approver_id: str, reason: str) -> str:
    """
    拒绝一条请假申请。

    参数:  request_id   - 申请编号
           approver_id  - 审批人工号
           reason       - 拒绝原因

    返回:  "已拒绝 lv_a1b2c3d4（年假 1.0天），原因：{reason}"
    """
    session = get_session()
    try:
        # 1. 查找申请
        result = session.execute(
            text("SELECT * FROM leave_requests WHERE id = :id"),
            {"id": request_id}
        )
        row = result.fetchone()
        if not row:
            return f"❌ 未找到编号为 {request_id} 的请假申请。"

        # 2. 校验状态
        if row.status != "pending":
            return f"❌ 该申请已被处理，无法重复审批。"

        # 3. 校验权限
        if row.approver_id and row.approver_id != approver_id:
            emp_result = session.execute(
                text("SELECT manager_id FROM employees WHERE id = :id"),
                {"id": row.employee_id}
            )
            emp_row = emp_result.fetchone()
            if not (emp_row and emp_row.manager_id == approver_id):
                return f"❌ 权限不足：该申请需上级审批。"

        # 4. 更新状态（不扣余额）
        resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.execute(
            text(
                "UPDATE leave_requests SET status='rejected', approver_id=:approver_id, "
                "approver_comment=:comment, resolved_at=:resolved_at WHERE id=:id"
            ),
            {
                "approver_id": approver_id,
                "comment": reason,
                "resolved_at": resolved_at,
                "id": request_id,
            }
        )
        session.commit()

        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假"
        }
        type_cn = type_names.get(row.leave_type, row.leave_type)

        return f"已拒绝 {request_id}（{type_cn} {row.days}天），原因：{reason}"
    finally:
        session.close()


def list_pending_approvals(manager_id: str) -> str:
    """
    列出等待某管理者审批的所有请假申请。

    参数:  manager_id - 管理者的工号

    返回:  "您有 2 条待审批请假：
           [lv_a1b2c3d4] 王小明 - 年假 1.0天 (2026-06-18) 理由：家里有事
           [lv_e5f6g7h8] 王小明 - 病假 2.0天 (2026-06-20至2026-06-21) 理由：发烧"
           如无待审批: "您目前没有待审批的请假申请。"
    """
    session = get_session()
    try:
        result = session.execute(
            text(
                "SELECT lr.id, lr.employee_id, lr.leave_type, lr.start_date, lr.end_date, lr.days, lr.reason, e.name "
                "FROM leave_requests lr "
                "JOIN employees e ON lr.employee_id = e.id "
                "WHERE lr.status = 'pending' AND lr.approver_id = :manager_id "
                "ORDER BY lr.created_at DESC"
            ),
            {"manager_id": manager_id}
        )
        rows = result.fetchall()

        if not rows:
            return "您目前没有待审批的请假申请。"

        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假"
        }

        lines = [f"您有 {len(rows)} 条待审批请假："]
        for row in rows:
            type_cn = type_names.get(row.leave_type, row.leave_type)
            date_range = row.start_date if row.start_date == row.end_date else f"{row.start_date}至{row.end_date}"
            reason_str = f" 理由：{row.reason}" if row.reason else ""
            lines.append(f"[{row.id}] {row.name} - {type_cn} {row.days}天 ({date_range}){reason_str}")

        return "\n".join(lines)
    finally:
        session.close()
