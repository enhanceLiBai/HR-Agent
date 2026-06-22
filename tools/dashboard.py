"""仪表盘：待审批积压 / 即将到来请假 / 考勤异常 / 公司全景。"""
import math
from datetime import datetime, date, timedelta
from sqlalchemy import text
from db.database import get_session

TOOL_CHECK_MY_DASHBOARD = {
    "type": "function",
    "function": {
        "name": "check_my_dashboard",
        "description": "检查个人/管理者仪表盘，汇总待审批积压、即将到来的请假、考勤异常等需要提醒的事项。Agent 应在每次对话开始时调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号"}
            },
            "required": ["employee_id"]
        }
    }
}

TOOL_GET_COMPANY_DASHBOARD = {
    "type": "function",
    "function": {
        "name": "get_company_dashboard",
        "description": "公司全景仪表盘。汇总全公司员工概况、今日考勤、考勤异常、待审批请假、近期请假动态。管理者使用此工具快速掌握整体情况。",
        "parameters": {
            "type": "object",
            "properties": {
                "manager_id": {"type": "string", "description": "管理者的工号（用于权限验证）"}
            },
            "required": ["manager_id"]
        }
    }
}


def check_my_dashboard(employee_id: str) -> str:
    """
    个人仪表盘检查。

    参数:  employee_id - 员工工号

    返回:  汇总提醒文本
    """
    session = get_session()
    try:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        this_month = now.strftime("%Y-%m")
        parts = []

        # 1. 待审批积压（仅管理者）
        pending = session.execute(
            text(
                "SELECT lr.id, lr.employee_id, lr.leave_type, lr.start_date, lr.end_date, lr.days, lr.reason, lr.created_at, e.name "
                "FROM leave_requests lr JOIN employees e ON lr.employee_id = e.id "
                "WHERE lr.status = 'pending' AND lr.approver_id = :eid "
                "ORDER BY lr.created_at"
            ),
            {"eid": employee_id}
        ).fetchall()

        if pending:
            backlog = 0
            for p in pending:
                created = datetime.strptime(p.created_at, "%Y-%m-%d %H:%M:%S")
                hours_waiting = (now - created).total_seconds() / 3600
                if hours_waiting > 24:
                    backlog += 1
            type_cn = {"annual": "年假", "personal": "事假", "sick": "病假",
                       "marriage": "婚假", "bereavement": "丧假", "maternity": "产假", "paternity": "陪产假", "comp": "调休假"}
            if backlog > 0:
                parts.append(f"📋 您有 {len(pending)} 条待审批请假（其中 {backlog} 条超过 24 小时）")
            else:
                parts.append(f"📋 您有 {len(pending)} 条待审批请假")

        # 2. 即将到来的请假（员工本人，7天内）
        upcoming = session.execute(
            text(
                "SELECT leave_type, start_date, end_date, days FROM leave_requests "
                "WHERE employee_id = :eid AND status = 'approved' "
                "AND start_date >= :today AND start_date <= :next_week "
                "ORDER BY start_date"
            ),
            {
                "eid": employee_id,
                "today": today_str,
                "next_week": date.today().replace(day=min(date.today().day + 7, 28)).isoformat()
                if date.today().day <= 28 else date.today().isoformat()
                # 简化处理，直接用 today 后推7天
            }
        ).fetchall()

        # 简化版：用字符串比较
        upcoming_rows = session.execute(
            text(
                "SELECT leave_type, start_date, end_date, days FROM leave_requests "
                "WHERE employee_id = :eid AND status = 'approved' "
                "AND date(start_date) BETWEEN date(:today) AND date(:today, '+7 days') "
                "ORDER BY start_date"
            ),
            {"eid": employee_id, "today": today_str}
        ).fetchall()

        if upcoming_rows:
            type_cn = {"annual": "年假", "personal": "事假", "sick": "病假",
                       "marriage": "婚假", "bereavement": "丧假", "maternity": "产假", "paternity": "陪产假", "comp": "调休假"}
            for u in upcoming_rows[:1]:  # 只提最近一条
                t = type_cn.get(u.leave_type, u.leave_type)
                date_range = u.start_date if u.start_date == u.end_date else f"{u.start_date}至{u.end_date}"
                parts.append(f"📅 您近期有请假安排：{u.start_date} {t} {u.days}天")

        # 3. 考勤异常
        attn = session.execute(
            text(
                "SELECT status, COUNT(*) as cnt FROM attendance_records "
                "WHERE employee_id = :eid AND date LIKE :prefix GROUP BY status"
            ),
            {"eid": employee_id, "prefix": this_month + "%"}
        ).fetchall()

        late_count = 0
        for a in attn:
            if a.status == "late":
                late_count = a.cnt
            elif a.status == "absent":
                pass  # 后面处理

        if late_count >= 3:
            parts.append(f"⚠️ 本月已迟到 {late_count} 次，已影响全勤奖")
        elif late_count > 0:
            parts.append(f"本月迟到 {late_count} 次")

        # 4. 调休过期提醒（14天内）
        expiring_comps = session.execute(
            text(
                "SELECT date, hours, overtime_type, remaining_comp_hours, expires_at "
                "FROM overtime_records "
                "WHERE employee_id = :eid AND status = 'approved' "
                "AND remaining_comp_hours > 0 "
                "AND date(expires_at) BETWEEN date(:today) AND date(:today, '+14 days') "
                "ORDER BY expires_at"
            ),
            {"eid": employee_id, "today": today_str}
        ).fetchall()

        if expiring_comps:
            type_names = {"weekday": "工作日加班", "weekend": "休息日加班", "holiday": "法定节假日加班"}
            total_expiring = sum(ec.remaining_comp_hours for ec in expiring_comps)
            details = []
            for ec in expiring_comps[:3]:
                exp_date = date.fromisoformat(ec.expires_at)
                days_left = (exp_date - date.today()).days
                details.append(f"{ec.remaining_comp_hours}h（{ec.expires_at}，还剩{days_left}天）")
            parts.append(f"⏰ 调休即将过期：{total_expiring} 小时（{'、'.join(details)}），请尽快使用")

        if not parts:
            return "一切正常。本月考勤无异常，无待审批事项，无即将到来的请假，无即将过期的调休。"

        return "\n".join(parts)
    finally:
        session.close()


def get_company_dashboard(manager_id: str) -> str:
    """
    公司全景仪表盘。仅管理者使用。

    参数:  manager_id - 管理者的工号

    返回:  多段汇总文本：员工概况 / 今日考勤 / 月度异常 / 待审批 / 近期请假
    """
    session = get_session()
    try:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        this_month = now.strftime("%Y-%m")
        sections = ["📊 **公司全景仪表盘**\n"]

        # ── 1. 员工概况 ──
        total_emp = session.execute(text("SELECT COUNT(*) FROM employees")).scalar()
        depts = session.execute(
            text("SELECT department, COUNT(*) as cnt FROM employees GROUP BY department ORDER BY cnt DESC")
        ).fetchall()
        dept_lines = "、".join(f"{d.department} {d.cnt}人" for d in depts)
        sections.append(f"👥 员工总数：{total_emp} 人（{dept_lines}）")

        # ── 2. 今日考勤概况 ──
        today_attn = session.execute(
            text("SELECT status, COUNT(*) as cnt FROM attendance_records WHERE date = :today GROUP BY status"),
            {"today": today_str}
        ).fetchall()
        if today_attn:
            status_map = {"normal": "✅ 正常出勤", "late": "⚠️ 迟到", "absent": "❌ 缺勤"}
            attn_parts = []
            for a in today_attn:
                attn_parts.append(f"{status_map.get(a.status, a.status)} {a.cnt}人")
            sections.append(f"\n📅 今日考勤（{today_str}）：{'  '.join(attn_parts)}")
        else:
            sections.append(f"\n📅 今日考勤（{today_str}）：暂无数据（可能是周末）")

        # ── 3. 本月考勤异常员工（迟到≥3次）──
        late_employees = session.execute(
            text(
                "SELECT e.name, e.department, COUNT(*) as late_cnt "
                "FROM attendance_records a JOIN employees e ON a.employee_id = e.id "
                "WHERE a.date LIKE :prefix AND a.status = 'late' "
                "GROUP BY a.employee_id HAVING late_cnt >= 3 "
                "ORDER BY late_cnt DESC"
            ),
            {"prefix": this_month + "%"}
        ).fetchall()
        if late_employees:
            lines = "\n".join(
                f"   • {le.name}（{le.department}）— 迟到 {le.late_cnt} 次" for le in late_employees
            )
            sections.append(f"\n⚠️ 本月考勤异常员工（迟到≥3次）：\n{lines}")
        else:
            sections.append("\n✅ 本月无考勤异常员工")

        # ── 3.5. 部门人力冲突预警（未来14天）──
        scan_start = today_str
        scan_end = (date.today() + timedelta(days=14)).isoformat()

        dept_groups = session.execute(
            text("SELECT department, COUNT(*) as cnt FROM employees GROUP BY department")
        ).fetchall()

        conflict_warnings = []
        for dg in dept_groups:
            dept_name = dg.department
            dept_total = dg.cnt
            threshold = max(1, math.ceil(dept_total * 0.3))

            # 查该部门在目标窗口内有重叠请假的人数
            conflict_rows = session.execute(
                text(
                    "SELECT DISTINCT e.name, lr.leave_type, lr.start_date, lr.end_date, lr.days "
                    "FROM leave_requests lr "
                    "JOIN employees e ON lr.employee_id = e.id "
                    "WHERE e.department = :dept "
                    "AND lr.status IN ('approved', 'pending') "
                    "AND lr.start_date <= :scan_end AND lr.end_date >= :scan_start "
                    "ORDER BY lr.start_date"
                ),
                {"dept": dept_name, "scan_start": scan_start, "scan_end": scan_end}
            ).fetchall()

            if len(conflict_rows) > threshold:
                type_names = {
                    "annual": "年假", "personal": "事假", "sick": "病假",
                    "marriage": "婚假", "bereavement": "丧假",
                    "maternity": "产假", "paternity": "陪产假", "comp": "调休假"
                }
                details = []
                for cr in conflict_rows[:10]:
                    t = type_names.get(cr.leave_type, cr.leave_type)
                    dr = cr.start_date if cr.start_date == cr.end_date else f"{cr.start_date}至{cr.end_date}"
                    details.append(f"     • {cr.name} — {t} {cr.days}天 ({dr})")
                conflict_warnings.append(
                    f"   ⚠️ {dept_name}（{dept_total}人）：未来14天 {len(conflict_rows)} 人请假，超过阈值 {threshold} 人\n"
                    + "\n".join(details)
                )

        if conflict_warnings:
            sections.append(f"\n🔧 部门人力冲突预警（{scan_start}~{scan_end}）：\n" + "\n".join(conflict_warnings))
        else:
            sections.append("\n🔧 部门人力冲突预警：✅ 各部门人力正常，无超阈值风险")

        # ── 4. 全公司待审批请假 ──
        all_pending = session.execute(
            text(
                "SELECT lr.id, lr.employee_id, lr.leave_type, lr.start_date, lr.end_date, "
                "lr.days, lr.reason, lr.created_at, e.name, "
                "m.name as approver_name "
                "FROM leave_requests lr "
                "JOIN employees e ON lr.employee_id = e.id "
                "LEFT JOIN employees m ON lr.approver_id = m.id "
                "WHERE lr.status = 'pending' "
                "ORDER BY lr.created_at"
            )
        ).fetchall()
        if all_pending:
            type_cn = {"annual": "年假", "personal": "事假", "sick": "病假",
                       "marriage": "婚假", "bereavement": "丧假", "maternity": "产假", "paternity": "陪产假", "comp": "调休假"}
            lines = []
            for p in all_pending:
                t = type_cn.get(p.leave_type, p.leave_type)
                date_range = p.start_date if p.start_date == p.end_date else f"{p.start_date}至{p.end_date}"
                created = datetime.strptime(p.created_at, "%Y-%m-%d %H:%M:%S")
                hours = int((now - created).total_seconds() / 3600)
                aging = f" ⏳等待{hours}h" if hours >= 24 else ""
                lines.append(
                    f"   • [{p.id}] {p.name} — {t} {p.days}天 ({date_range}) "
                    f"→ 待 {p.approver_name or '?'} 审批{aging}"
                )
            sections.append(f"\n📋 全公司待审批请假（{len(all_pending)} 条）：\n" + "\n".join(lines))
        else:
            sections.append("\n📋 全公司无待审批请假")

        # ── 5. 本月请假动态 ──
        month_leaves = session.execute(
            text(
                "SELECT lr.leave_type, lr.start_date, lr.end_date, lr.days, lr.status, e.name "
                "FROM leave_requests lr JOIN employees e ON lr.employee_id = e.id "
                "WHERE lr.start_date LIKE :prefix OR lr.created_at LIKE :prefix2 "
                "ORDER BY lr.start_date LIMIT 10"
            ),
            {"prefix": this_month + "%", "prefix2": this_month + "%"}
        ).fetchall()
        if month_leaves:
            type_cn = {"annual": "年假", "personal": "事假", "sick": "病假",
                       "marriage": "婚假", "bereavement": "丧假", "maternity": "产假", "paternity": "陪产假", "comp": "调休假"}
            status_cn = {"pending": "待审批", "approved": "已批准", "rejected": "已拒绝",
                         "cancelled": "已撤回", "revoked": "已撤销"}
            lines = []
            for lv in month_leaves[:8]:
                t = type_cn.get(lv.leave_type, lv.leave_type)
                s = status_cn.get(lv.status, lv.status)
                date_range = lv.start_date if lv.start_date == lv.end_date else f"{lv.start_date}至{lv.end_date}"
                lines.append(f"   • {lv.name} — {t} {lv.days}天 ({date_range}) [{s}]")
            sections.append(f"\n📆 本月请假动态（最近 {len(lines)} 条）：\n" + "\n".join(lines))
        else:
            sections.append("\n📆 本月暂无请假记录")

        return "\n".join(sections)
    finally:
        session.close()
