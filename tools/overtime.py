"""加班相关工具函数：提交 / 审批 / 拒绝 / 查调休余额。"""
import secrets
from datetime import datetime, date
from sqlalchemy import text
from db.database import get_session

TOOL_SUBMIT_OVERTIME = {
    "type": "function",
    "function": {
        "name": "submit_overtime",
        "description": "提交加班记录（事后提交制）。员工加班后提交加班日期、小时数、类型和原因。系统自动计算调休时长。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "加班人工号"},
                "date": {"type": "string", "description": "加班日期，格式 YYYY-MM-DD"},
                "hours": {"type": "number", "description": "实际加班小时数"},
                "overtime_type": {
                    "type": "string",
                    "enum": ["weekday", "weekend", "holiday"],
                    "description": "加班类型：weekday(工作日加班×1.5)、weekend(休息日加班×2.0)、holiday(法定节假日加班×3.0)"
                },
                "reason": {"type": "string", "description": "加班原因"}
            },
            "required": ["employee_id", "date", "hours", "overtime_type", "reason"]
        }
    }
}

TOOL_APPROVE_OVERTIME = {
    "type": "function",
    "function": {
        "name": "approve_overtime",
        "description": "审批通过一条加班记录。通过后系统自动计算调休时长并记入员工调休余额。仅管理者使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "加班记录编号（ot_开头的ID）"},
                "approver_id": {"type": "string", "description": "审批人工号"},
                "comment": {"type": "string", "description": "审批意见（可选）"}
            },
            "required": ["request_id", "approver_id"]
        }
    }
}

TOOL_REJECT_OVERTIME = {
    "type": "function",
    "function": {
        "name": "reject_overtime",
        "description": "拒绝一条加班记录。仅管理者使用。需填写拒绝原因。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "加班记录编号（ot_开头的ID）"},
                "approver_id": {"type": "string", "description": "审批人工号"},
                "reason": {"type": "string", "description": "拒绝原因"}
            },
            "required": ["request_id", "approver_id", "reason"]
        }
    }
}

TOOL_QUERY_OVERTIME_BALANCE = {
    "type": "function",
    "function": {
        "name": "query_overtime_balance",
        "description": "查询员工的调休余额，包含明细和即将过期（14天内）的提醒。员工可随时查询自己的调休情况。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号"}
            },
            "required": ["employee_id"]
        }
    }
}

# ── 加班类型倍率 ──
OVERTIME_RATES = {
    "weekday": 1.5,
    "weekend": 2.0,
    "holiday": 3.0,
}

TYPE_NAMES = {
    "weekday": "工作日加班",
    "weekend": "休息日加班",
    "holiday": "法定节假日加班",
}


def submit_overtime(
    employee_id: str,
    date_str: str,
    hours: float,
    overtime_type: str,
    reason: str
) -> str:
    """
    员工提交加班记录（事后提交制）。

    参数:  employee_id   - 加班人工号
           date_str      - 加班日期 "YYYY-MM-DD"
           hours         - 实际加班小时数
           overtime_type - weekday / weekend / holiday
           reason        - 加班原因

    返回:  确认信息
    """
    if overtime_type not in OVERTIME_RATES:
        return f"❌ 无效的加班类型: {overtime_type}。有效类型: weekday, weekend, holiday"

    session = get_session()
    try:
        request_id = "ot_" + secrets.token_hex(4)

        # 计算折算调休
        rate = OVERTIME_RATES[overtime_type]
        comp_hours = hours * rate

        # 计算过期日期（加班日期 + 3个月）
        d = date.fromisoformat(date_str)
        # 简单加3个月
        exp_month = d.month + 3
        exp_year = d.year
        if exp_month > 12:
            exp_month -= 12
            exp_year += 1
        # 处理月末边界
        import calendar
        last_day = calendar.monthrange(exp_year, exp_month)[1]
        exp_day = min(d.day, last_day)
        expires_at = f"{exp_year}-{exp_month:02d}-{exp_day:02d}"

        # 获取默认审批人
        approver_id = None
        approver_name = "上级"
        emp_result = session.execute(
            text("SELECT manager_id, name FROM employees WHERE id = :id"),
            {"id": employee_id}
        )
        emp_row = emp_result.fetchone()
        if emp_row and emp_row.manager_id:
            approver_id = emp_row.manager_id
            mgr_result = session.execute(
                text("SELECT name FROM employees WHERE id = :id"),
                {"id": emp_row.manager_id}
            )
            mgr_row = mgr_result.fetchone()
            if mgr_row:
                approver_name = mgr_row.name

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        session.execute(
            text(
                "INSERT INTO overtime_records (id, employee_id, date, hours, overtime_type, "
                "comp_hours, remaining_comp_hours, expires_at, reason, status, approver_id, created_at) "
                "VALUES (:id, :employee_id, :date, :hours, :overtime_type, "
                ":comp_hours, 0, :expires_at, :reason, 'pending', :approver_id, :created_at)"
            ),
            {
                "id": request_id,
                "employee_id": employee_id,
                "date": date_str,
                "hours": hours,
                "overtime_type": overtime_type,
                "comp_hours": comp_hours,
                "expires_at": expires_at,
                "reason": reason,
                "approver_id": approver_id,
                "created_at": created_at,
            }
        )
        session.commit()

        type_name = TYPE_NAMES.get(overtime_type, overtime_type)
        return (
            f"✅ 加班记录已提交（编号 {request_id}）\n"
            f"日期：{date_str}  加班：{hours} 小时  类型：{type_name}（×{rate}）\n"
            f"折算调休：{comp_hours} 小时  有效期至：{expires_at}\n"
            f"状态：等待 {approver_name} 审批"
        )
    finally:
        session.close()


def approve_overtime(request_id: str, approver_id: str, comment: str = "") -> str:
    """
    审批通过一条加班记录，并自动更新调休余额。

    参数:  request_id  - 加班记录编号
           approver_id - 审批人工号
           comment     - 审批意见（可选）

    返回:  确认信息
    """
    session = get_session()
    try:
        result = session.execute(
            text("SELECT * FROM overtime_records WHERE id = :id"),
            {"id": request_id}
        )
        row = result.fetchone()
        if not row:
            return f"❌ 未找到编号为 {request_id} 的加班记录。"

        if row.status != "pending":
            return f"❌ 该加班记录已被处理，无法重复审批。"

        # 权限校验
        if row.approver_id and row.approver_id != approver_id:
            emp_result = session.execute(
                text("SELECT manager_id FROM employees WHERE id = :id"),
                {"id": row.employee_id}
            )
            emp_row = emp_result.fetchone()
            if not (emp_row and emp_row.manager_id == approver_id):
                return f"❌ 权限不足：该加班记录需上级审批。"

        resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.execute(
            text(
                "UPDATE overtime_records SET status='approved', approver_id=:approver_id, "
                "approver_comment=:comment, resolved_at=:resolved_at, "
                "remaining_comp_hours=:comp_hours WHERE id=:id"
            ),
            {
                "approver_id": approver_id,
                "comment": comment if comment else "",
                "resolved_at": resolved_at,
                "comp_hours": row.comp_hours,
                "id": request_id,
            }
        )

        # 更新 leave_balances 中的 comp 余额
        existing = session.execute(
            text(
                "SELECT id, total, used FROM leave_balances "
                "WHERE employee_id = :eid AND leave_type = 'comp' AND year = 2026"
            ),
            {"eid": row.employee_id}
        ).fetchone()
        if existing:
            session.execute(
                text(
                    "UPDATE leave_balances SET total = total + :comp "
                    "WHERE employee_id = :eid AND leave_type = 'comp' AND year = 2026"
                ),
                {"comp": row.comp_hours, "eid": row.employee_id}
            )
        else:
            session.execute(
                text(
                    "INSERT INTO leave_balances (employee_id, leave_type, total, used, year) "
                    "VALUES (:eid, 'comp', :comp, 0, 2026)"
                ),
                {"eid": row.employee_id, "comp": row.comp_hours}
            )

        session.commit()

        type_name = TYPE_NAMES.get(row.overtime_type, row.overtime_type)

        # 查询当前总余额
        bal = session.execute(
            text(
                "SELECT total, used FROM leave_balances "
                "WHERE employee_id = :eid AND leave_type = 'comp' AND year = 2026"
            ),
            {"eid": row.employee_id}
        ).fetchone()
        current_balance = (bal.total - bal.used) if bal else row.comp_hours

        return (
            f"✅ 已批准 {request_id}（{type_name} {row.hours}h → 调休 {row.comp_hours}h），有效期至 {row.expires_at}。\n"
            f"当前调休余额：{current_balance} 小时。"
        )
    finally:
        session.close()


def reject_overtime(request_id: str, approver_id: str, reason: str) -> str:
    """
    拒绝一条加班记录。

    参数:  request_id  - 加班记录编号
           approver_id - 审批人工号
           reason      - 拒绝原因

    返回:  确认信息
    """
    session = get_session()
    try:
        result = session.execute(
            text("SELECT * FROM overtime_records WHERE id = :id"),
            {"id": request_id}
        )
        row = result.fetchone()
        if not row:
            return f"❌ 未找到编号为 {request_id} 的加班记录。"

        if row.status != "pending":
            return f"❌ 该加班记录已被处理，无法重复审批。"

        if row.approver_id and row.approver_id != approver_id:
            emp_result = session.execute(
                text("SELECT manager_id FROM employees WHERE id = :id"),
                {"id": row.employee_id}
            )
            emp_row = emp_result.fetchone()
            if not (emp_row and emp_row.manager_id == approver_id):
                return f"❌ 权限不足：该加班记录需上级审批。"

        resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.execute(
            text(
                "UPDATE overtime_records SET status='rejected', approver_id=:approver_id, "
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

        type_name = TYPE_NAMES.get(row.overtime_type, row.overtime_type)
        return f"已拒绝 {request_id}（{type_name} {row.hours}h），原因：{reason}"
    finally:
        session.close()


def query_overtime_balance(employee_id: str) -> str:
    """
    查询员工的调休余额，含即将过期的部分。

    参数:  employee_id - 工号

    返回:  调休余额汇总 + 明细 + 过期提醒
    """
    session = get_session()
    try:
        today = date.today()
        today_str = today.isoformat()

        # 查询所有已批准且还有剩余调休的记录
        rows = session.execute(
            text(
                "SELECT id, date, hours, overtime_type, comp_hours, remaining_comp_hours, expires_at "
                "FROM overtime_records "
                "WHERE employee_id = :eid AND status = 'approved' AND remaining_comp_hours > 0 "
                "AND date(expires_at) >= date(:today) "
                "ORDER BY expires_at"
            ),
            {"eid": employee_id, "today": today_str}
        ).fetchall()

        if not rows:
            return "🏖️ 调休余额：0 小时。如有加班请提交加班记录。"

        total_balance = sum(r.remaining_comp_hours for r in rows)

        # 检查即将过期的（14天内）
        expiring_soon = []
        for r in rows:
            exp_date = date.fromisoformat(r.expires_at)
            days_left = (exp_date - today).days
            if days_left <= 14:
                expiring_soon.append((r, days_left))

        lines = [f"🏖️ 调休余额：{total_balance} 小时"]

        if expiring_soon:
            exp_parts = []
            for r, days_left in expiring_soon:
                exp_parts.append(f"{r.remaining_comp_hours} 小时（{r.expires_at} 到期，还剩 {days_left} 天）")
            lines.append(f"⚠️ 即将过期：{'、'.join(exp_parts)}")
        else:
            lines.append("⚠️ 即将过期：无")

        lines.append("")
        lines.append("明细：")
        for r in rows:
            type_name = TYPE_NAMES.get(r.overtime_type, r.overtime_type)
            lines.append(
                f"• {r.date} 加班 {r.hours}h（{type_name} ×{OVERTIME_RATES.get(r.overtime_type, '?')}）= {r.comp_hours}h，"
                f"剩余 {r.remaining_comp_hours}h，有效期至 {r.expires_at}"
            )

        return "\n".join(lines)
    finally:
        session.close()


# ── 管理者查看待审批加班记录 ──

TOOL_LIST_PENDING_OVERTIME = {
    "type": "function",
    "function": {
        "name": "list_pending_overtime",
        "description": "列出等待某管理者审批的所有加班记录。仅管理者使用。返回待审批的加班记录及员工信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "manager_id": {"type": "string", "description": "管理者的工号"}
            },
            "required": ["manager_id"]
        }
    }
}


def list_pending_overtime(manager_id: str) -> str:
    """
    列出等待某管理者审批的所有加班记录。

    参数:  manager_id - 管理者的工号

    返回:  "您有 2 条待审批加班记录：
           [ot_a1b2c3d4] 王小明 - 工作日加班 3.0h (2026-06-17) → 调休 4.5h 理由：项目联调
           [ot_e5f6g7h8] 李经理 - 休息日加班 4.0h (2026-06-14) → 调休 8.0h 理由：服务器维护"
           如无待审批: "您目前没有待审批的加班记录。"
    """
    session = get_session()
    try:
        rows = session.execute(
            text(
                "SELECT ot.id, ot.employee_id, ot.date, ot.hours, ot.overtime_type, "
                "ot.comp_hours, ot.reason, ot.created_at, e.name "
                "FROM overtime_records ot "
                "JOIN employees e ON ot.employee_id = e.id "
                "WHERE ot.status = 'pending' AND ot.approver_id = :manager_id "
                "ORDER BY ot.created_at DESC"
            ),
            {"manager_id": manager_id}
        ).fetchall()

        if not rows:
            return "您目前没有待审批的加班记录。"

        lines = [f"您有 {len(rows)} 条待审批加班记录："]
        for r in rows:
            type_name = TYPE_NAMES.get(r.overtime_type, r.overtime_type)
            reason_str = f" 理由：{r.reason}" if r.reason else ""
            lines.append(
                f"[{r.id}] {r.name} - {type_name} {r.hours}h ({r.date}) → 调休 {r.comp_hours}h{reason_str}"
            )

        return "\n".join(lines)
    finally:
        session.close()
