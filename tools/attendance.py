"""考勤工具：查询打卡记录 / 月度统计。"""
from datetime import date
from sqlalchemy import text
from db.database import get_session

TOOL_QUERY_MY_ATTENDANCE = {
    "type": "function",
    "function": {
        "name": "query_my_attendance",
        "description": "查询员工的每日考勤打卡记录。可按月份筛选。员工只能查自己的，管理者可以查下属的。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号"},
                "month": {"type": "string", "description": "月份，格式 YYYY-MM，如 2026-06。不传则默认当前月。"}
            },
            "required": ["employee_id"]
        }
    }
}

TOOL_GET_ATTENDANCE_STATS = {
    "type": "function",
    "function": {
        "name": "get_attendance_stats",
        "description": "查询员工某月的考勤统计数据：正常出勤天数、迟到次数、缺勤天数。用于快速了解考勤概况。",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "员工工号"},
                "month": {"type": "string", "description": "月份，格式 YYYY-MM，如 2026-06。不传则默认当前月。"}
            },
            "required": ["employee_id"]
        }
    }
}

WEEKDAYS_CN = {
    0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"
}


def query_my_attendance(employee_id: str, month: str = "2026-06") -> str:
    """
    查询某个员工某个月的每日考勤打卡记录。

    参数:  employee_id - 员工工号
           month       - 月份 "YYYY-MM"，默认当前月

    返回:  格式化的考勤记录列表
    """
    session = get_session()
    try:
        # 先查员工姓名
        emp = session.execute(
            text("SELECT name FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        if not emp:
            return f"未找到工号为 {employee_id} 的员工。"

        rows = session.execute(
            text(
                "SELECT date, check_in, check_out, status FROM attendance_records "
                "WHERE employee_id = :eid AND date LIKE :prefix ORDER BY date"
            ),
            {"eid": employee_id, "prefix": month + "%"}
        ).fetchall()

        if not rows:
            year, mon = month.split("-")
            return f"{year}年{int(mon)}月暂无考勤记录。"

        lines = [f"{emp.name} {month.replace('-', '年')}月考勤记录（共 {len(rows)} 个工作日）："]
        for r in rows:
            d = date.fromisoformat(r.date)
            wd = WEEKDAYS_CN[d.weekday()]
            check_in = r.check_in or "--:--"
            check_out = r.check_out or "--:--"
            icon = {"normal": "✅ 正常", "late": "⚠️ 迟到", "absent": "❌ 缺勤"}.get(r.status, r.status)
            lines.append(f"  {r.date[5:]} {wd}  {check_in}-{check_out} {icon}")

        # 统计
        normal = sum(1 for r in rows if r.status == "normal")
        late = sum(1 for r in rows if r.status == "late")
        absent = sum(1 for r in rows if r.status == "absent")
        parts = []
        if normal: parts.append(f"正常 {normal} 次")
        if late: parts.append(f"迟到 {late} 次")
        if absent: parts.append(f"缺勤 {absent} 次")
        lines.append(f"\n  📊 {' | '.join(parts)}")

        return "\n".join(lines)
    finally:
        session.close()


def get_attendance_stats(employee_id: str, month: str = "2026-06") -> str:
    """
    查询某员工某月的考勤统计数据。

    参数:  employee_id - 员工工号
           month       - 月份 "YYYY-MM"，默认当前月

    返回:  格式化的考勤统计
    """
    session = get_session()
    try:
        emp = session.execute(
            text("SELECT name FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()
        if not emp:
            return f"未找到工号为 {employee_id} 的员工。"

        rows = session.execute(
            text(
                "SELECT date, status FROM attendance_records "
                "WHERE employee_id = :eid AND date LIKE :prefix ORDER BY date"
            ),
            {"eid": employee_id, "prefix": month + "%"}
        ).fetchall()

        if not rows:
            year, mon = month.split("-")
            return f"{year}年{int(mon)}月暂无考勤数据。"

        normal = sum(1 for r in rows if r.status == "normal")
        late = sum(1 for r in rows if r.status == "late")
        absent = sum(1 for r in rows if r.status == "absent")

        # 迟到日期列表
        late_dates = [r.date[5:] for r in rows if r.status == "late"]

        year, mon = month.split("-")
        lines = [f"{emp.name} {year}年{int(mon)}月考勤统计："]
        lines.append(f"  正常出勤：{normal} 天")
        lines.append(f"  迟到：{late} 天" + (f"（{', '.join(late_dates)}）" if late_dates else ""))
        lines.append(f"  缺勤：{absent} 天")

        if late >= 3:
            lines.append(f"  ⚠️ 当月迟到超过3次，已影响全勤奖。")

        return "\n".join(lines)
    finally:
        session.close()
