"""撤回 + 撤销功能专项测试（无需 LLM，纯本地、秒出结果）"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass


def reset_db():
    db_path = os.path.join(os.path.dirname(__file__), "hr.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    from db.database import init_db
    init_db()


def test():
    from tools.leave import (
        create_leave_request, approve_leave, reject_leave,
        cancel_leave_request, revoke_leave_request,
        query_leave_balance,
    )
    from tools.employee import get_my_leave_history

    errors = []

    def check(desc, condition, detail=""):
        status = "✅" if condition else "❌"
        print(f"  {status} {desc}")
        if not condition:
            errors.append(f"{desc}: {detail}")

    # ═══════════════════════════════════════
    print("=" * 65)
    print("  撤回 (cancel) 与 撤销 (revoke) 专项测试")
    print("=" * 65)

    # ── 场景 1：员工正常撤回 pending 申请 ──
    print("\n📌 场景1 — 员工撤回 pending 申请")

    r = create_leave_request("emp_003", "personal", "2026-06-25", "2026-06-25", "临时有事")
    req_id = r.split("编号 ")[1].split("）")[0]
    print(f"  提交申请: {req_id}")

    r = cancel_leave_request(req_id, "emp_003")
    check("撤回应成功", "已撤回" in r, r)
    check("余额未受影响", "余额未受影响" in r, r)
 
    r = cancel_leave_request(req_id, "emp_003")
    check("重复撤回应被拒绝", "已撤回" in r or "无需重复" in r, r)

    # ── 场景 2：非本人不能撤回 ──
    print("\n📌 场景2 — 非本人不能撤回")

    r = create_leave_request("emp_003", "personal", "2026-06-26", "2026-06-26", "测试")
    req_id = r.split("编号 ")[1].split("）")[0]
    print(f"  王小明提交: {req_id}")

    r = cancel_leave_request(req_id, "emp_002")  # 李经理试图撤回
    check("非本人不能撤回", "只能撤回自己" in r, r)

    # ── 场景 3：approved 的申请不能 cancel，要走 revoke ──
    print("\n📌 场景3 — approved 状态不能 cancel")

    r = create_leave_request("emp_002", "annual", "2026-07-05", "2026-07-05", "测试撤销")
    req_id = r.split("编号 ")[1].split("）")[0]
    approve_leave(req_id, "emp_001", "同意")
    print(f"  李经理申请年假 {req_id}，张总已批准")

    r = cancel_leave_request(req_id, "emp_002")
    check("approved 状态不能 cancel", "无法撤回" in r and "撤销流程" in r, r)

    # ── 场景 4：管理者撤销已批准但未开始的申请 ──
    print("\n📌 场景4 — 管理者撤销 approved 且未开始的申请")

    bal_before = query_leave_balance("emp_002", "annual")
    print(f"  撤销前余额: {bal_before}")

    r = revoke_leave_request(req_id, "emp_001", "项目延期，需要你在")
    check("撤销应成功", "已撤销" in r, r)
    check("应退回年假余额", "已退回" in r, r)

    bal_after = query_leave_balance("emp_002", "annual")
    print(f"  撤销后余额: {bal_after}")

    # ── 场景 5：假期已开始不能撤销 ──
    print("\n📌 场景5 — 假期已开始不能撤销")

    r = create_leave_request("emp_002", "annual", "2026-06-01", "2026-06-01", "过去的日期")
    req_id = r.split("编号 ")[1].split("）")[0]
    approve_leave(req_id, "emp_001", "同意")
    print(f"  李经理申请过去日期 {req_id}，张总已批准")

    r = revoke_leave_request(req_id, "emp_001", "撤销")
    check("已开始的假不能撤销", "已开始" in r or "无法撤销" in r, r)

    # ── 场景 6：rejected 的申请不能 cancel ──
    print("\n📌 场景6 — rejected 状态不能 cancel")

    r = create_leave_request("emp_003", "personal", "2026-06-28", "2026-06-28", "测试拒绝后撤回")
    req_id = r.split("编号 ")[1].split("）")[0]
    reject_leave(req_id, "emp_002", "不同意")
    print(f"  王小明提交 {req_id}，李经理已拒绝")

    r = cancel_leave_request(req_id, "emp_003")
    check("rejected 状态不能 cancel", "无需重复" in r or "已拒绝" in r, r)

    # ── 场景 7：非审批人不能 revoke ──
    print("\n📌 场景7 — 非审批人不能 revoke")

    r = create_leave_request("emp_002", "annual", "2026-08-01", "2026-08-01", "测试权限")
    req_id = r.split("编号 ")[1].split("）")[0]
    approve_leave(req_id, "emp_001", "同意")
    print(f"  李经理申请 {req_id}，张总已批准")

    r = revoke_leave_request(req_id, "emp_003", "我来撤销")  # 王小明没有权限
    check("非审批人不能撤销", "权限不足" in r, r)

    # ── 汇总 ──
    print(f"\n{'=' * 65}")
    if errors:
        print(f"  ❌ 失败 {len(errors)} 项：")
        for e in errors:
            print(f"     - {e}")
    else:
        print("  ✅ 全部通过！")
    print(f"{'=' * 65}")


if __name__ == "__main__":
    reset_db()
    test()
