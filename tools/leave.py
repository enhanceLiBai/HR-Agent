"""请假相关工具函数。"""
import secrets
from datetime import datetime, date
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
                    "enum": ["annual", "personal", "sick", "marriage", "bereavement", "maternity", "paternity", "comp"],
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
        "description": "创建请假申请。只有在制度合规、余额充足的前提下才调用此工具。如果前面 check_auto_approval 返回全部通过，传 auto_approve=true 实现自动审批。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "申请人工号"},
                "leave_type": {"type": "string", "description": "假期类型"},
                "start_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD，单天与 start_date 相同"},
                "reason": {"type": "string", "description": "请假原因"},
                "auto_approve": {"type": "boolean", "description": "是否自动审批。仅当 check_auto_approval 全部条件通过时传 true，否则传 false 或不传。"}
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

TOOL_CANCEL_LEAVE_REQUEST = {
    "type": "function",
    "function": {
        "name": "cancel_leave_request",
        "description": "员工撤回自己提交的、还在等待审批的请假申请。只有状态为 pending 且为申请人本人操作的才能撤回。不涉及余额变动。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "申请编号"},
                "employee_id": {"type": "string", "description": "申请人工号（必须是申请人本人）"}
            },
            "required": ["request_id", "employee_id"]
        }
    }
}

TOOL_REVOKE_LEAVE_REQUEST = {
    "type": "function",
    "function": {
        "name": "revoke_leave_request",
        "description": "管理者撤销一条已批准但假期尚未开始的申请。撤销后余额退回。仅管理者使用。如果假期已开始则需走销假流程。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "申请编号"},
                "approver_id": {"type": "string", "description": "审批人工号"},
                "reason": {"type": "string", "description": "撤销原因"}
            },
            "required": ["request_id", "approver_id", "reason"]
        }
    }
}

TOOL_CHECK_AUTO_APPROVAL = {
    "type": "function",
    "function": {
        "name": "check_auto_approval",
        "description": "检查一个请假申请是否符合自动审批条件。返回每个条件（假期类型、天数、提前量、余额、上级）的通过/失败状态。在请假流程中，合规检查和余额查询完成后，创建申请前调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "申请人工号"},
                "leave_type": {"type": "string", "description": "假期类型"},
                "start_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD"},
                "days": {"type": "number", "description": "请假天数"}
            },
            "required": ["employee_id", "leave_type", "start_date", "end_date", "days"]
        }
    }
}

TOOL_CHECK_DEPARTMENT_CONFLICT = {
    "type": "function",
    "function": {
        "name": "check_department_conflict",
        "description": "检查同一部门内在相同时段请假的员工人数是否超过阈值。返回冲突信息作为预警，不阻止提交。员工请假前可调用此工具了解部门同期请假情况。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "申请人工号"},
                "start_date": {"type": "string", "description": "申请的开始日期，格式 YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "申请的结束日期，格式 YYYY-MM-DD"}
            },
            "required": ["employee_id", "start_date", "end_date"]
        }
    }
}

TOOL_ADJUST_LEAVE_BALANCE = {
    "type": "function",
    "function": {
        "name": "adjust_leave_balance",
        "description": "管理者手动调整下属员工的假期余额配额。正数增加总额，负数扣减总额。仅直属上级可操作，原因必填并记入审计日志。",
        "parameters": {
            "type": "object",
            "properties": {
                "manager_id": {"type": "string", "description": "执行操作的管理者工号（权限校验用）"},
                "employee_id": {"type": "string", "description": "目标员工工号"},
                "leave_type": {
                    "type": "string",
                    "enum": ["annual", "personal", "sick", "marriage", "bereavement", "maternity", "paternity", "comp"],
                    "description": "假期类型"
                },
                "amount": {"type": "number", "description": "调整值（天数）：正数=增加配额，负数=扣减配额。调整后总配额不能低于已使用值。"},
                "reason": {"type": "string", "description": "调整原因（必填，写入审计日志）"}
            },
            "required": ["manager_id", "employee_id", "leave_type", "amount", "reason"]
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
    valid_types = ["annual", "personal", "sick", "marriage", "bereavement", "maternity", "paternity", "comp"]
    if leave_type not in valid_types:
        return f"❌ 无效的假期类型: {leave_type}。有效类型: {', '.join(valid_types)}"

    type_names = {
        "annual": "年假", "personal": "事假", "sick": "病假",
        "marriage": "婚假", "bereavement": "丧假",
        "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
    }

    # comp 类型转调休余额查询
    if leave_type == "comp":
        from tools.overtime import query_overtime_balance
        return query_overtime_balance(employee_id)

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
            # 事假/病假等无限额类型不需要存量记录，直接返回"不设额度"
            name_cn = type_names.get(leave_type, leave_type)
            return f"{name_cn}：不设额度，暂无使用记录。"

        total = row.total
        used = row.used
        remaining = total - used
        name_cn = type_names.get(leave_type, leave_type)

        # 无限额类型（事假/病假 total=0），只显示用量
        if total == 0:
            if used == 0:
                return f"{name_cn}：不设额度，暂无使用记录。"
            else:
                return f"{name_cn}：不设额度，已使用 {used} 天。"

        # 有额度类型，显示剩余
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
    reason: str,
    auto_approve: bool = False
) -> str:
    """
    创建一条请假申请，状态为 pending（或 approved，如果 auto_approve=True）。

    参数:  employee_id  - 申请人工号
           leave_type    - 假期类型
           start_date    - 开始日期 "YYYY-MM-DD"
           end_date      - 结束日期 "YYYY-MM-DD"（单天则等于 start_date）
           reason        - 请假原因
           auto_approve  - 是否自动审批（仅当 check_auto_approval 全部通过时为 True）

    返回:  "✅ 请假申请已提交（编号 lv_a1b2c3d4）
           类型：年假  日期：2026-06-18 至 2026-06-18  天数：1.0天
           状态：等待 李经理 审批"

           自动审批时：
           "✅ 请假申请已自动通过（编号 lv_a1b2c3d4）
           类型：年假  日期：2026-06-18 至 2026-06-18  天数：1.0天
           状态：系统自动审批（符合自动审批条件），年假余额已扣除。"

    注意:  此函数不做合规检查，合规检查由 Agent 在调用前完成。
           auto_approve 参数是 Agent 基于 check_auto_approval 结果做出的决定。
    """
    session = get_session()
    try:
        # 1. 生成唯一 ID
        request_id = "lv_" + secrets.token_hex(4)

        # 2. 计算天数
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        days = (e - s).days + 1.0

        # 年假/调休支持半天/小时：单天 + reason 中提到"半天" → 0.5
        if leave_type in ("annual", "comp") and start_date == end_date and "半天" in reason:
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
                approver_name = "无（自动通过）"

        # 4. 核对假期类型名称
        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
        }
        type_cn = type_names.get(leave_type, leave_type)

        # 5. 自动审批路径
        if auto_approve:
            # 再次验证自动审批条件（防御性检查）
            auto_ok, auto_msg = _verify_auto_approval(
                employee_id, leave_type, start_date, days
            )
            if auto_ok:
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                resolved_at = created_at

                session.execute(
                    text(
                        "INSERT INTO leave_requests (id, employee_id, leave_type, start_date, end_date, "
                        "days, reason, status, approver_id, approver_comment, created_at, resolved_at) "
                        "VALUES (:id, :employee_id, :leave_type, :start_date, :end_date, "
                        ":days, :reason, 'approved', 'SYSTEM', :comment, :created_at, :resolved_at)"
                    ),
                    {
                        "id": request_id,
                        "employee_id": employee_id,
                        "leave_type": leave_type,
                        "start_date": start_date,
                        "end_date": end_date,
                        "days": days,
                        "reason": reason,
                        "comment": "系统自动审批：年假≤1天+余额充足+提前≥1天",
                        "created_at": created_at,
                        "resolved_at": resolved_at,
                    }
                )

                # 扣减余额
                _deduct_balance(session, employee_id, leave_type, days)
                session.commit()

                return (
                    f"✅ 请假申请已自动通过（编号 {request_id}）\n"
                    f"类型：{type_cn}  日期：{start_date} 至 {end_date}  天数：{days}天\n"
                    f"状态：系统自动审批（符合自动审批条件），{type_cn}余额已扣除。"
                )
            # 自动审批条件不满足 → 降级为普通 pending

        # 6. 正常插入 pending 记录
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

        # 如果无上级（总经理），自动通过
        if not approver_id:
            approve_leave(request_id, employee_id, "无上级，自动通过")
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

        # 4. 校验余额充足性（带薪假期 / 调休）
        # 注：personal(事假)/sick(病假) 也在此追踪用量，但 total=0 时不校验额度
        paid_types = ["annual", "marriage", "bereavement", "maternity", "paternity", "personal", "sick"]
        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
        }
        if row.leave_type in paid_types:
            bal = session.execute(
                text(
                    "SELECT total, used FROM leave_balances "
                    "WHERE employee_id = :eid AND leave_type = :ltype AND year = 2026"
                ),
                {"eid": row.employee_id, "ltype": row.leave_type}
            ).fetchone()
            if not bal:
                # 余额记录缺失时自动创建（total=0），不影响审批流程
                session.execute(
                    text("INSERT INTO leave_balances (employee_id, leave_type, total, used, year) "
                         "VALUES (:eid, :ltype, 0, 0, 2026)"),
                    {"eid": row.employee_id, "ltype": row.leave_type}
                )
                # 重新查询，使后续逻辑统一
                bal = session.execute(
                    text("SELECT total, used FROM leave_balances "
                         "WHERE employee_id = :eid AND leave_type = :ltype AND year = 2026"),
                    {"eid": row.employee_id, "ltype": row.leave_type}
                ).fetchone()
            # 只有设置了额度（total>0）的类型才校验余额充足性
            # personal/sick 的 total=0 表示无限额，只追踪用量不校验额度
            if bal.total > 0:
                remaining = bal.total - bal.used
                if remaining < row.days:
                    type_cn = type_names.get(row.leave_type, row.leave_type)
                    return (f"❌ 审批失败：{type_cn}余额不足（需要 {row.days} 天，"
                            f"剩余 {remaining} 天）。")
        elif row.leave_type == "comp":
            # 检查调休余额是否充足
            comp_bal = session.execute(
                text(
                    "SELECT COALESCE(SUM(remaining_comp_hours), 0) as total_hours "
                    "FROM overtime_records "
                    "WHERE employee_id = :eid AND status = 'approved' "
                    "AND remaining_comp_hours > 0 AND date(:today) <= date(expires_at)"
                ),
                {"eid": row.employee_id, "today": date.today().isoformat()}
            ).fetchone()
            remaining_hours = comp_bal.total_hours or 0
            needed_hours = row.days * 8
            if remaining_hours < needed_hours:
                return (f"❌ 审批失败：调休余额不足（需要 {needed_hours} 小时，"
                        f"剩余 {remaining_hours} 小时）。")

        # 5. 更新状态
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

        # 6. 带薪假期扣减额度
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
        elif row.leave_type == "comp":
            # 调休假：扣减 overtime_records 中的剩余调休 + 更新 leave_balances
            _deduct_balance(session, row.employee_id, "comp", row.days)

        session.commit()

        type_cn = type_names.get(row.leave_type, row.leave_type)

        if row.leave_type in paid_types or row.leave_type == "comp":
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
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
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
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
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


def cancel_leave_request(request_id: str, employee_id: str) -> str:
    """
    员工撤回自己提交的、状态为 pending 的请假申请。

    参数:  request_id  - 申请编号
           employee_id - 撤回人的工号（必须是申请人本人）

    返回:  "✅ 已撤回 lv_a1b2c3d4（年假 1.0天），余额未受影响。"
           或 "❌ 该申请状态为'已批准'，无法撤回。如需取消请走撤销流程。"
           或 "❌ 只能撤回自己的请假申请。"
    """
    session = get_session()
    try:
        result = session.execute(
            text("SELECT * FROM leave_requests WHERE id = :id"),
            {"id": request_id}
        )
        row = result.fetchone()
        if not row:
            return f"❌ 未找到编号为 {request_id} 的请假申请。"

        # 校验状态
        if row.status != "pending":
            status_names = {
                "approved": "已批准", "rejected": "已拒绝",
                "cancelled": "已撤回", "revoked": "已撤销", "completed_early": "已销假"
            }
            status_cn = status_names.get(row.status, row.status)
            if row.status == "approved":
                return f"❌ 该申请状态为'{status_cn}'，无法撤回。如需取消请走撤销流程（由管理者审批）。"
            return f"❌ 该申请状态为'{status_cn}'，无需重复操作。"

        # 校验本人操作
        if row.employee_id != employee_id:
            return f"❌ 只能撤回自己的请假申请。"

        # 更新状态
        resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.execute(
            text(
                "UPDATE leave_requests SET status='cancelled', resolved_at=:resolved_at "
                "WHERE id=:id"
            ),
            {"resolved_at": resolved_at, "id": request_id}
        )
        session.commit()

        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
        }
        type_cn = type_names.get(row.leave_type, row.leave_type)

        return f"✅ 已撤回 {request_id}（{type_cn} {row.days}天），余额未受影响。"
    finally:
        session.close()


def revoke_leave_request(request_id: str, approver_id: str, reason: str) -> str:
    """
    管理者审批撤销一条已批准但假期尚未开始的申请。

    参数:  request_id  - 申请编号
           approver_id - 审批人工号
           reason      - 撤销原因

    返回:  "✅ 已撤销 lv_a1b2c3d4（年假 1.0天），已退回年假余额 1.0 天。"
           或 "❌ 该申请状态不是'已批准'，无法撤销。"
           或 "❌ 假期已开始（2026-06-15），无法撤销。请走销假流程。"
           或 "❌ 权限不足：该申请需上级审批。"
    """
    session = get_session()
    try:
        result = session.execute(
            text("SELECT * FROM leave_requests WHERE id = :id"),
            {"id": request_id}
        )
        row = result.fetchone()
        if not row:
            return f"❌ 未找到编号为 {request_id} 的请假申请。"

        # 校验状态必须是 approved
        if row.status != "approved":
            status_names = {
                "pending": "待审批", "rejected": "已拒绝",
                "cancelled": "已撤回", "revoked": "已撤销", "completed_early": "已销假"
            }
            status_cn = status_names.get(row.status, row.status)
            return f"❌ 该申请状态为'{status_cn}'，不是'已批准'，无法撤销。"

        # 校验假期尚未开始
        today = date.today()
        start = date.fromisoformat(row.start_date)
        if start <= today:
            return f"❌ 假期已开始（{row.start_date}），无法撤销。请走销假流程。"

        # 校验权限（与 approve_leave 相同的权限逻辑）
        if row.approver_id and row.approver_id != approver_id:
            emp_result = session.execute(
                text("SELECT manager_id FROM employees WHERE id = :id"),
                {"id": row.employee_id}
            )
            emp_row = emp_result.fetchone()
            if not (emp_row and emp_row.manager_id == approver_id):
                return f"❌ 权限不足：该申请需上级审批。"

        # 更新状态
        resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.execute(
            text(
                "UPDATE leave_requests SET status='revoked', approver_id=:approver_id, "
                "approver_comment=:comment, resolved_at=:resolved_at WHERE id=:id"
            ),
            {
                "approver_id": approver_id,
                "comment": reason,
                "resolved_at": resolved_at,
                "id": request_id,
            }
        )

        # 退回带薪假期余额（含事假/病假的用量追踪）
        paid_types = ["annual", "marriage", "bereavement", "maternity", "paternity", "personal", "sick"]
        if row.leave_type in paid_types:
            session.execute(
                text(
                    "UPDATE leave_balances SET used = used - :days "
                    "WHERE employee_id = :employee_id AND leave_type = :leave_type AND year = 2026"
                ),
                {
                    "days": row.days,
                    "employee_id": row.employee_id,
                    "leave_type": row.leave_type,
                }
            )
        elif row.leave_type == "comp":
            # 退回调休余额：leave_balances 退回 + overtime_records 退回剩余小时
            session.execute(
                text(
                    "UPDATE leave_balances SET used = used - :days "
                    "WHERE employee_id = :employee_id AND leave_type = 'comp' AND year = 2026"
                ),
                {"days": row.days, "employee_id": row.employee_id}
            )
            # 将折算的小时数退回到最早过期的加班记录（与扣减时的 FIFO 顺序一致）
            hours_to_refund = row.days * 8
            ot_records = session.execute(
                text(
                    "SELECT id, comp_hours, remaining_comp_hours FROM overtime_records "
                    "WHERE employee_id = :eid AND status = 'approved' "
                    "AND date(:today) <= date(expires_at) "
                    "ORDER BY expires_at"
                ),
                {"eid": row.employee_id, "today": date.today().isoformat()}
            ).fetchall()
            for ot in ot_records:
                if hours_to_refund <= 0:
                    break
                space = ot.comp_hours - ot.remaining_comp_hours
                add_back = min(space, hours_to_refund)
                if add_back > 0:
                    session.execute(
                        text(
                            "UPDATE overtime_records SET remaining_comp_hours = remaining_comp_hours + :add "
                            "WHERE id = :id"
                        ),
                        {"add": add_back, "id": ot.id}
                    )
                    hours_to_refund -= add_back

        session.commit()

        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
        }
        type_cn = type_names.get(row.leave_type, row.leave_type)

        if row.leave_type in paid_types or row.leave_type == "comp":
            return f"✅ 已撤销 {request_id}（{type_cn} {row.days}天），已退回{type_cn}余额 {row.days} 天。"
        else:
            return f"✅ 已撤销 {request_id}（{type_cn} {row.days}天）。"
    finally:
        session.close()


# ── 内部辅助函数 ──

def _verify_auto_approval(employee_id: str, leave_type: str, start_date: str, days: float) -> tuple:
    """
    内部防御性检查：验证自动审批条件是否全部满足。
    返回 (bool, str)。
    """
    # 条件1: 仅年假或调休
    if leave_type not in ("annual", "comp"):
        return False, f"假期类型 {leave_type} 不支持自动审批"

    # 条件2: 天数 ≤ 1
    if days > 1.0:
        return False, f"天数 {days} > 1"

    # 条件3: 提前 ≥ 1 天
    today = date.today()
    start = date.fromisoformat(start_date)
    if (start - today).days < 1:
        return False, f"提前量不足1天"

    # 条件4: 余额充足
    session = get_session()
    try:
        bal = session.execute(
            text(
                "SELECT total, used FROM leave_balances "
                "WHERE employee_id = :eid AND leave_type = :ltype AND year = 2026"
            ),
            {"eid": employee_id, "ltype": leave_type}
        ).fetchone()
        if not bal:
            return False, f"无 {leave_type} 假期余额记录"
        if bal.total - bal.used < days:
            return False, f"余额不足"
    finally:
        session.close()

    # 条件5: 有上级
    session2 = get_session()
    try:
        emp = session2.execute(
            text("SELECT manager_id FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        if not emp or not emp.manager_id:
            return False, "无直属上级"
    finally:
        session2.close()

    return True, "全部通过"


def _deduct_balance(session, employee_id: str, leave_type: str, days: float):
    """扣减假期/调休余额。"""
    if leave_type == "comp":
        # 调休从 overtime_records 中扣减
        rows = session.execute(
            text(
                "SELECT id, remaining_comp_hours FROM overtime_records "
                "WHERE employee_id = :eid AND status = 'approved' AND remaining_comp_hours > 0 "
                "AND date(:today) <= date(expires_at) "
                "ORDER BY expires_at"
            ),
            {"eid": employee_id, "today": date.today().isoformat()}
        ).fetchall()

        remaining_to_deduct = days * 8  # 1天 = 8小时调休
        for r in rows:
            if remaining_to_deduct <= 0:
                break
            deduct = min(r.remaining_comp_hours, remaining_to_deduct)
            session.execute(
                text(
                    "UPDATE overtime_records SET remaining_comp_hours = remaining_comp_hours - :deduct "
                    "WHERE id = :id"
                ),
                {"deduct": deduct, "id": r.id}
            )
            remaining_to_deduct -= deduct

        # 更新 leave_balances
        total_used = days * 8  # 转换回小时记录
        session.execute(
            text(
                "UPDATE leave_balances SET used = used + :used "
                "WHERE employee_id = :eid AND leave_type = 'comp' AND year = 2026"
            ),
            {"used": days, "eid": employee_id}
        )
    else:
        paid_types = ["annual", "marriage", "bereavement", "maternity", "paternity", "personal", "sick"]
        if leave_type in paid_types:
            session.execute(
                text(
                    "UPDATE leave_balances SET used = used + :days "
                    "WHERE employee_id = :eid AND leave_type = :ltype AND year = 2026"
                ),
                {"days": days, "eid": employee_id, "ltype": leave_type}
            )


# ── 公开工具函数 ──

def check_auto_approval(
    employee_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float
) -> str:
    """
    检查一个请假申请是否符合自动审批条件。

    自动审批条件（全部满足）：
        1. leave_type 为 annual 或 comp
        2. days <= 1.0
        3. 提前 ≥ 1 天：today + 1 <= start_date
        4. 余额充足
        5. 有上级：employees.manager_id IS NOT NULL

    参数:  employee_id - 申请人工号
           leave_type   - 假期类型
           start_date   - 开始日期 "YYYY-MM-DD"
           end_date     - 结束日期 "YYYY-MM-DD"
           days         - 请假天数

    返回:  通过/失败状态（每条件逐一列出）
    """
    today = date.today()
    start = date.fromisoformat(start_date)

    # 逐项检查
    checks = []

    # 条件1: 类型
    type_ok = leave_type in ("annual", "comp")
    type_cn = {"annual": "年假", "comp": "调休"}.get(leave_type, leave_type)
    checks.append(("假期类型", f"{type_cn}", type_ok))

    # 条件2: 天数
    days_ok = days <= 1.0
    checks.append(("天数", f"{days}天 ≤ 1天", days_ok))

    # 条件3: 提前
    days_ahead = (start - today).days
    ahead_ok = days_ahead >= 1
    checks.append(("提前申请", f"提前 {days_ahead} 天", ahead_ok))

    # 条件4: 余额
    session = get_session()
    try:
        if leave_type == "comp":
            bal_rows = session.execute(
                text(
                    "SELECT SUM(remaining_comp_hours) as total FROM overtime_records "
                    "WHERE employee_id = :eid AND status = 'approved' AND remaining_comp_hours > 0 "
                    "AND date(:today) <= date(expires_at)"
                ),
                {"eid": employee_id, "today": today.isoformat()}
            ).fetchone()
            remaining_hours = bal_rows.total or 0
            remaining_days = remaining_hours / 8
        else:
            bal = session.execute(
                text(
                    "SELECT total, used FROM leave_balances "
                    "WHERE employee_id = :eid AND leave_type = :ltype AND year = 2026"
                ),
                {"eid": employee_id, "ltype": leave_type}
            ).fetchone()
            remaining_days = (bal.total - bal.used) if bal else 0

        balance_ok = remaining_days >= days
        checks.append(("余额", f"剩余 {remaining_days}天 ≥ {days}天", balance_ok))
    finally:
        session.close()

    # 条件5: 有上级
    session2 = get_session()
    try:
        emp = session2.execute(
            text("SELECT manager_id FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        has_manager = emp and emp.manager_id is not None
        checks.append(("审批路径", "有直属上级" if has_manager else "无直属上级", has_manager))
    finally:
        session2.close()

    # 汇总
    all_pass = all(c[2] for c in checks)
    lines = []
    if all_pass:
        lines.append("✅ 符合自动审批条件：")
    else:
        lines.append("❌ 不符合自动审批条件：")

    for name, detail, ok in checks:
        mark = "✓" if ok else "✗"
        if all_pass:
            lines.append(f" • {name}：{detail} {mark}")
        else:
            extra = "" if ok else f"（{_fail_reason(name, detail)}）"
            lines.append(f" • {name}：{detail} {mark}{extra}")

    if all_pass:
        lines.append("\n该申请将自动通过，无需等待审批。")
    else:
        lines.append("\n该申请将走正常审批流程。")

    return "\n".join(lines)


def _fail_reason(name: str, detail: str) -> str:
    """简短说明条件未通过的原因。"""
    reasons = {
        "假期类型": "仅年假和调休支持自动审批",
        "天数": "请假天数超过 1 天",
        "提前申请": "需至少提前 1 天",
        "余额": "余额不足",
        "审批路径": "总经理无上级审批人，不走自动审批",
    }
    return reasons.get(name, "")


def check_department_conflict(
    employee_id: str,
    start_date: str,
    end_date: str
) -> str:
    """
    检查同一部门内在相同时段请假的员工人数是否超过阈值。

    参数:  employee_id - 申请人工号
           start_date   - 申请的开始日期
           end_date     - 申请的结束日期

    返回:  冲突预警信息
    """
    session = get_session()
    try:
        # 获取员工部门
        emp = session.execute(
            text("SELECT department, name FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        if not emp:
            return "无法检查部门冲突：未找到员工部门信息。"

        dept = emp.department

        # 部门总人数
        dept_count = session.execute(
            text("SELECT COUNT(*) FROM employees WHERE department = :dept"),
            {"dept": dept}
        ).scalar()

        # 阈值：max(1, ceil(30%))
        import math
        threshold = max(1, math.ceil(dept_count * 0.3))

        # 查同期请假冲突（含 approved 和 pending）
        conflicts = session.execute(
            text(
                "SELECT DISTINCT e.name, lr.leave_type, lr.start_date, lr.end_date, lr.days "
                "FROM leave_requests lr "
                "JOIN employees e ON lr.employee_id = e.id "
                "WHERE e.department = :dept "
                "AND lr.status IN ('approved', 'pending') "
                "AND lr.start_date <= :end_date AND lr.end_date >= :start_date "
                "AND lr.employee_id != :eid "
                "ORDER BY lr.start_date"
            ),
            {"dept": dept, "start_date": start_date, "end_date": end_date, "eid": employee_id}
        ).fetchall()

        conflict_count = len(conflicts) + 1  # +1 包含申请人自己

        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
        }

        if conflict_count > threshold:
            lines = [
                f"⚠️ 部门人力冲突预警：",
                f"您的部门（{dept}）共 {dept_count} 人，同期请假 {conflict_count} 人（含您），超过预警阈值 {threshold} 人。",
                f"同期请假员工："
            ]
            for c in conflicts:
                t = type_names.get(c.leave_type, c.leave_type)
                date_range = c.start_date if c.start_date == c.end_date else f"{c.start_date}至{c.end_date}"
                if c.start_date == c.end_date:
                    lines.append(f" • {c.name}（{c.start_date} {t} {c.days}天）")
                else:
                    lines.append(f" • {c.name}（{date_range} {t} {c.days}天）")
            lines.append("")
            lines.append("此为预警提醒，不阻止您提交请假。建议与主管沟通排班。")
            return "\n".join(lines)
        else:
            return f"✅ 部门人力正常：{dept}共 {dept_count} 人，同期请假 {conflict_count} 人，未超过预警阈值。"
    finally:
        session.close()


def adjust_leave_balance(
    manager_id: str,
    employee_id: str,
    leave_type: str,
    amount: float,
    reason: str
) -> str:
    """
    管理者手动调整下属员工的假期余额配额。

    参数:  manager_id  - 执行操作的管理者工号（必须是目标员工的直属上级）
           employee_id - 目标员工工号
           leave_type  - 假期类型
           amount      - 调整值（天数）：正数增加配额，负数扣减配额
           reason      - 调整原因（必填，记入审计日志）

    返回:  成功或失败信息（含调整前后对比）
    """
    # ── 输入验证 ──
    valid_types = ["annual", "personal", "sick", "marriage", "bereavement",
                   "maternity", "paternity", "comp"]
    if leave_type not in valid_types:
        return (f"❌ 无效假期类型: {leave_type}。"
                f"有效类型: {', '.join(valid_types)}")

    if amount == 0:
        return "❌ 调整金额不能为 0。"

    if not reason or not reason.strip():
        return "❌ 调整原因不能为空。"

    session = get_session()
    try:
        # ── 1. 验证员工是否存在 ──
        emp = session.execute(
            text("SELECT id, name FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        if not emp:
            return f"❌ 未找到员工 {employee_id}。"

        # ── 2. 权限校验：manager_id 必须是 employee_id 的直属上级 ──
        mgr_rel = session.execute(
            text("SELECT manager_id FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        if not (mgr_rel and mgr_rel.manager_id == manager_id):
            mgr = session.execute(
                text("SELECT name FROM employees WHERE id = :id"),
                {"id": manager_id}
            ).fetchone()
            mgr_name = mgr.name if mgr else manager_id

            actual_mgr = session.execute(
                text("SELECT e.name FROM employees e "
                     "JOIN employees emp ON emp.manager_id = e.id "
                     "WHERE emp.id = :eid"),
                {"eid": employee_id}
            ).fetchone()
            actual_name = actual_mgr[0] if actual_mgr else "无"

            return (f"❌ 权限不足：{mgr_name} 不是 {emp.name} 的直属上级"
                    f"（{emp.name} 的上级是 {actual_name}）。")

        # ── 3. 查找现有余额记录 ──
        year = 2026
        bal = session.execute(
            text("SELECT id, total, used FROM leave_balances "
                 "WHERE employee_id = :eid AND leave_type = :ltype AND year = :year"),
            {"eid": employee_id, "ltype": leave_type, "year": year}
        ).fetchone()

        old_total = 0.0
        old_used = 0.0
        bal_id = None

        if bal:
            old_total = bal.total
            old_used = bal.used
            bal_id = bal.id
        else:
            if amount < 0:
                type_names = {
                    "annual": "年假", "personal": "事假", "sick": "病假",
                    "marriage": "婚假", "bereavement": "丧假",
                    "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
                }
                cn = type_names.get(leave_type, leave_type)
                return (f"❌ {emp.name} 没有 {cn} 余额记录，无法扣减。"
                        f"请先通过加班或额度分配创建记录。")

        # ── 4. 余额下限约束 ──
        remaining = old_total - old_used
        new_total = old_total + amount
        new_remaining = remaining + amount

        if new_remaining < 0:
            type_names = {
                "annual": "年假", "personal": "事假", "sick": "病假",
                "marriage": "婚假", "bereavement": "丧假",
                "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
            }
            cn = type_names.get(leave_type, leave_type)
            return (f"❌ 操作失败：{emp.name} 的 {cn} 当前剩余 {remaining} 天，"
                    f"扣减 {abs(amount)} 天后余额为 {new_remaining} 天（不能为负）。")

        # ── 5. 执行更新 ──
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if bal_id:
            session.execute(
                text("UPDATE leave_balances SET total = total + :amount WHERE id = :id"),
                {"amount": amount, "id": bal_id}
            )
        else:
            session.execute(
                text("INSERT INTO leave_balances (employee_id, leave_type, total, used, year) "
                     "VALUES (:eid, :ltype, :total, 0, :year)"),
                {"eid": employee_id, "ltype": leave_type, "total": amount, "year": year}
            )

        # ── 6. 写入审计日志 ──
        session.execute(
            text("INSERT INTO leave_balance_adjustments "
                 "(employee_id, leave_type, old_total, new_total, "
                 "old_used, new_used, amount, adjusted_by, reason, created_at) "
                 "VALUES (:eid, :ltype, :ot, :nt, :ou, :nu, :amt, :by, :rsn, :now)"),
            {
                "eid": employee_id,
                "ltype": leave_type,
                "ot": old_total,
                "nt": new_total,
                "ou": old_used,
                "nu": old_used,
                "amt": amount,
                "by": manager_id,
                "rsn": reason.strip(),
                "now": now,
            }
        )

        session.commit()

        # ── 7. 返回结果 ──
        type_names = {
            "annual": "年假", "personal": "事假", "sick": "病假",
            "marriage": "婚假", "bereavement": "丧假",
            "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
        }
        cn = type_names.get(leave_type, leave_type)
        action = "增加" if amount > 0 else "扣减"
        abs_amt = abs(amount)

        return (
            f"✅ 已{action} {emp.name} 的 {cn} 额度 {abs_amt} 天\n"
            f"调整前：总额 {old_total} 天，已用 {old_used} 天，剩余 {remaining} 天\n"
            f"调整后：总额 {new_total} 天，已用 {old_used} 天，剩余 {new_remaining} 天\n"
            f"原因：{reason}"
        )
    finally:
        session.close()
