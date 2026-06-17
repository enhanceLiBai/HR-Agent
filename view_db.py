"""数据库可视化查看工具。"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from db.database import get_session


def main():
    session = get_session()
    try:
        # ── 员工表 ──
        print("=" * 70)
        print("  👥 员工列表")
        print("=" * 70)
        rows = session.execute(text("SELECT id, name, department, position, manager_id, hire_date FROM employees")).fetchall()
        print(f"{'工号':<10} {'姓名':<8} {'部门':<8} {'职位':<8} {'上级':<8} {'入职日期':<12}")
        print("-" * 70)
        for r in rows:
            mgr = r.manager_id or "无"
            print(f"{r.id:<10} {r.name:<8} {r.department:<8} {r.position:<8} {mgr:<8} {r.hire_date:<12}")

        # ── 假期余额表 ──
        print(f"\n{'=' * 70}")
        print("  📊 假期余额 (2026年)")
        print("=" * 70)
        rows = session.execute(text(
            "SELECT lb.employee_id, e.name, lb.leave_type, lb.total, lb.used, lb.total - lb.used as remaining "
            "FROM leave_balances lb JOIN employees e ON lb.employee_id = e.id "
            "WHERE lb.year = 2026 ORDER BY lb.employee_id, lb.leave_type"
        )).fetchall()
        type_cn = {"annual": "年假", "personal": "事假", "sick": "病假",
                   "marriage": "婚假", "bereavement": "丧假", "maternity": "产假", "paternity": "陪产假"}
        print(f"{'员工':<10} {'类型':<8} {'总额':<6} {'已用':<6} {'剩余':<6}")
        print("-" * 70)
        for r in rows:
            name = type_cn.get(r.leave_type, r.leave_type)
            remaining = r.total - r.used
            flag = " ⚠已用完" if remaining <= 0 else ""
            print(f"{r.name}({r.employee_id}):<10 {name:<8} {r.total:<6.1f} {r.used:<6.1f} {remaining:<6.1f}{flag}")

        # ── 请假申请表 ──
        print(f"\n{'=' * 70}")
        print("  📋 请假申请记录")
        print("=" * 70)
        rows = session.execute(text(
            "SELECT lr.id, e.name, lr.leave_type, lr.start_date, lr.end_date, lr.days, lr.status, lr.approver_comment, lr.created_at "
            "FROM leave_requests lr JOIN employees e ON lr.employee_id = e.id "
            "ORDER BY lr.created_at DESC"
        )).fetchall()
        status_cn = {"pending": "⏳待审批", "approved": "✅已批准", "rejected": "❌已拒绝"}
        if not rows:
            print("  (暂无记录)")
        for r in rows:
            name = type_cn.get(r.leave_type, r.leave_type)
            status = status_cn.get(r.status, r.status)
            date_range = r.start_date if r.start_date == r.end_date else f"{r.start_date} ~ {r.end_date}"
            comment = f" | {r.approver_comment}" if r.approver_comment else ""
            print(f"  [{r.id}] {r.name} | {name} {r.days}天 | {date_range} | {status}{comment}")
            print(f"           提交时间: {r.created_at}")

        print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
