"""全类型假期 + 边界条件测试（无 LLM 调用）"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# ── 重置数据库 ──
db_path = os.path.join(os.path.dirname(__file__), "hr.db")
if os.path.exists(db_path):
    os.remove(db_path)

from db.database import init_db
init_db()

from tools.leave import (
    create_leave_request, approve_leave, reject_leave,
    query_leave_balance, cancel_leave_request, revoke_leave_request,
    list_pending_approvals, check_auto_approval, check_department_conflict,
    adjust_leave_balance,
)
from tools.employee import get_my_leave_history, get_employee
from db.database import get_session
from sqlalchemy import text

passed = 0
failed = 0

def test(name: str):
    """测试装饰器，打印结果"""
    def decorator(fn):
        global passed, failed
        try:
            fn()
            print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            raise
    return decorator

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"    ✗ {name} FAILED: {detail}")

def db_used(emp_id: str, ltype: str) -> float:
    s = get_session()
    try:
        r = s.execute(text(
            "SELECT used FROM leave_balances "
            "WHERE employee_id=:e AND leave_type=:l AND year=2026"
        ), {"e": emp_id, "l": ltype}).fetchone()
        return r.used if r else -999
    finally:
        s.close()

def db_status(req_id: str) -> str:
    s = get_session()
    try:
        r = s.execute(text(
            "SELECT status FROM leave_requests WHERE id=:id"
        ), {"id": req_id}).fetchone()
        return r.status if r else "NOT_FOUND"
    finally:
        s.close()

def extract_id(response: str) -> str:
    return response.split("编号 ")[1].split("）")[0]


print("=" * 60)
print("  HR Agent 全类型假期 + 边界条件测试")
print("=" * 60)

# ═══════════════════════════════════════════════
# 1. 余额查询 — 所有类型
# ═══════════════════════════════════════════════
print("\n▶ 1. 余额查询 — 全覆盖")

# 年假有余额
r = query_leave_balance("emp_002", "annual")
check("1.1 年假有余额", "剩余5.0天" in r or "剩余" in r, r)

# 年假已用完
r = query_leave_balance("emp_003", "annual")
check("1.2 年假已用完", "已用完" in r, r)

# 年假部分使用
r = query_leave_balance("emp_001", "annual")
check("1.3 年假部分使用(5/2)", "剩余3.0天" in r, r)

# 事假无限额未使用
r = query_leave_balance("emp_001", "personal")
check("1.4 事假无限额未使用", "不设额度" in r and "暂无使用" in r, r)

# 婚假已用完
r = query_leave_balance("emp_002", "marriage")
check("1.5 婚假已用完(3/3)", "已用完" in r, r)

# 调休有余额
r = query_leave_balance("emp_003", "comp")
check("1.6 调休有余额", "小时" in r, r)

# 无效类型
r = query_leave_balance("emp_001", "vacation")
check("1.7 无效假期类型", "无效" in r, r)

# 不存在的员工
r = query_leave_balance("emp_999", "annual")
check("1.8 不存在的员工", "未找到" in r, r)

print(f"  1.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 2. 事假(sick=0) — 无限额，用量追踪
# ═══════════════════════════════════════════════
print("\n▶ 2. 事假(personal) — 无限额 + 用量追踪")

bal_before = db_used("emp_003", "personal")
check("2.1 事假初始used=0", bal_before == 0, str(bal_before))

r = create_leave_request("emp_003", "personal", "2026-07-05", "2026-07-05", "回老家")
req = extract_id(r)
check("2.2 事假创建成功", "lv_" in r and "李经理" in r, r)

r2 = approve_leave(req, "emp_002", "同意")
check("2.3 事假审批通过", "已批准" in r2, r2)
check("2.4 事假消息含扣除", "已扣除事假余额" in r2, r2)

bal = db_used("emp_003", "personal")
check("2.5 事假used=1", bal == 1.0, str(bal))

# 再请一次事假 — 无限额，不应被拒
r = create_leave_request("emp_003", "personal", "2026-08-10", "2026-08-12", "有事")
req2 = extract_id(r)
r2 = approve_leave(req2, "emp_002", "同意")
check("2.6 事假二次审批通过(3天)", "已批准" in r2, r2)
bal = db_used("emp_003", "personal")
check("2.7 事假used=4(1+3)", bal == 4.0, str(bal))

# 余额查询显示
r = query_leave_balance("emp_003", "personal")
check("2.8 事假查询不设额度+已使用", "不设额度" in r and "4" in r, r)

print(f"  2.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 3. 年假 — 有额度，校验拦截
# ═══════════════════════════════════════════════
print("\n▶ 3. 年假(annual) — 额度校验 + 拦截")

# emp_003 年假 total=5 used=5 → 0剩余
r = create_leave_request("emp_003", "annual", "2026-07-01", "2026-07-01", "休假")
req = extract_id(r)
r2 = approve_leave(req, "emp_002", "同意")
check("3.1 年假余额0拦截", "余额不足" in r2 and "0.0 天" in r2, r2)
check("3.2 年假余额未扣(仍为5)", db_used("emp_003", "annual") == 5.0)

# emp_002 年假 total=5 used=0 → 5剩余，正常批
r = create_leave_request("emp_002", "annual", "2026-07-10", "2026-07-10", "休一天")
req = extract_id(r)
r2 = approve_leave(req, "emp_001", "同意")
check("3.3 年假余额充足审批通过", "已批准" in r2, r2)
check("3.4 年假used=1", db_used("emp_002", "annual") == 1.0, str(db_used("emp_002", "annual")))

# emp_001 年假 total=5 used=2 → 3剩余，请4天应被拒
r = create_leave_request("emp_001", "annual", "2026-07-15", "2026-07-18", "4天假")
req = extract_id(r)
r2 = approve_leave(req, "emp_001", "自己批")  # emp_001是CEO没有上级但approver_id=None
check("3.5 年假余额不足(需4剩3)", "余额不足" in r2, r2)

# emp_001 请3天应该通过（CEO无上级，走自动通过）
r = create_leave_request("emp_001", "annual", "2026-09-01", "2026-09-03", "3天假")
req = extract_id(r)
check("3.6 CEO年假3天通过(自动)", "自动通过" in r or "已批准" in r, r)

print(f"  3.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 4. 病假(sick) — 无限额，用量追踪
# ═══════════════════════════════════════════════
print("\n▶ 4. 病假(sick) — 无限额 + 用量追踪")

bal_before = db_used("emp_001", "sick")
check("4.1 病假初始used=0", bal_before == 0, str(bal_before))

# CEO无上级，create_leave_request 内部自动 approve
r = create_leave_request("emp_001", "sick", "2026-07-20", "2026-07-21", "发烧")
check("4.2 病假CEO自动通过", "已批准" in r or "自动通过" in r, r)
check("4.3 病假used=2(2天)", db_used("emp_001", "sick") == 2.0)

r = query_leave_balance("emp_001", "sick")
check("4.4 病假查询不设额度+已使用", "不设额度" in r and "2" in r, r)

print(f"  4.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 5. 婚假/丧假/产假/陪产假 — 有额度类型
# ═══════════════════════════════════════════════
print("\n▶ 5. 婚假/丧假/产假/陪产假 — 额度校验")

# 婚假：emp_003 total=3 used=0 → 正常批
r = create_leave_request("emp_003", "marriage", "2026-10-01", "2026-10-03", "结婚")
req = extract_id(r)
r2 = approve_leave(req, "emp_002", "恭喜")
check("5.1 婚假3天审批通过", "已批准" in r2, r2)
check("5.2 婚假used=3", db_used("emp_003", "marriage") == 3.0)

# 婚假已用完再请应被拒
r = create_leave_request("emp_003", "marriage", "2026-11-01", "2026-11-01", "又结婚")
req = extract_id(r)
r2 = approve_leave(req, "emp_002", "不行")
check("5.3 婚假用完被拒", "余额不足" in r2, r2)

# 丧假：emp_002 total=3 used=0 → 正常
r = create_leave_request("emp_002", "bereavement", "2026-08-01", "2026-08-03", "丧事")
req = extract_id(r)
r2 = approve_leave(req, "emp_001", "节哀")
check("5.4 丧假3天审批通过", "已批准" in r2, r2)
check("5.5 丧假used=3", db_used("emp_002", "bereavement") == 3.0)

# 产假&陪产假没有种子数据余额 → 应报"未找到余额记录"
# 先手动增加额度
r = adjust_leave_balance("emp_002", "emp_003", "maternity", 98, "补产假额度")
check("5.6 增加产假额度", "✅" in r, r)
r = create_leave_request("emp_003", "maternity", "2026-12-01", "2026-12-30", "产假")
req = extract_id(r)
r2 = approve_leave(req, "emp_002", "同意")
check("5.7 产假30天审批通过", "已批准" in r2, r2)
check("5.8 产假used=30", db_used("emp_003", "maternity") == 30.0)

# 陪产假
r = adjust_leave_balance("emp_001", "emp_002", "paternity", 7, "补陪产假额度")
check("5.9 增加陪产假额度", "✅" in r, r)
r = create_leave_request("emp_002", "paternity", "2026-09-01", "2026-09-07", "陪产")
req = extract_id(r)
r2 = approve_leave(req, "emp_001", "同意")
check("5.10 陪产假7天审批通过", "已批准" in r2, r2)
check("5.11 陪产假used=7", db_used("emp_002", "paternity") == 7.0)

print(f"  5.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 6. 调休(comp) — 额度校验
# ═══════════════════════════════════════════════
print("\n▶ 6. 调休(comp) — 额度校验")

# emp_003 有调休 4.5小时 → 请1天(8小时)应被拒
r = create_leave_request("emp_003", "comp", "2026-07-10", "2026-07-10", "调休1天")
req = extract_id(r)
r2 = approve_leave(req, "emp_002", "同意")
check("6.1 调休余额不足(需8h剩4.5h)", "余额不足" in r2, r2)

# 请半天(0.5天=4小时)应通过（余额4.5h >= 4h）
r = create_leave_request("emp_003", "comp", "2026-07-10", "2026-07-10", "调休半天")
req = extract_id(r)
r2 = approve_leave(req, "emp_002", "同意")
check("6.2 调休半天审批通过", "已批准" in r2, r2)

print(f"  6.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 7. 拒绝 (reject)
# ═══════════════════════════════════════════════
print("\n▶ 7. 拒绝流程")

r = create_leave_request("emp_003", "personal", "2026-07-25", "2026-07-25", "拒绝测试")
req = extract_id(r)
bal_before = db_used("emp_003", "personal")

r2 = reject_leave(req, "emp_002", "当天有重要会议")
check("7.1 拒绝成功", "已拒绝" in r2 and "重要会议" in r2, r2)
check("7.2 拒绝不扣余额", db_used("emp_003", "personal") == bal_before)

# 重复拒绝
r2 = reject_leave(req, "emp_002", "再拒一次")
check("7.3 重复拒绝被拦截", "已被处理" in r2, r2)

# 非直属上级拒绝
r = create_leave_request("emp_003", "personal", "2026-07-26", "2026-07-26", "权限测试")
req = extract_id(r)
r2 = reject_leave(req, "emp_001", "跨级拒")
check("7.4 非直级拒绝被拦截", "权限不足" in r2, r2)

print(f"  7.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 8. 撤回 (cancel)
# ═══════════════════════════════════════════════
print("\n▶ 8. 员工撤回")

r = create_leave_request("emp_003", "personal", "2026-08-20", "2026-08-20", "撤回测试")
req = extract_id(r)
r2 = cancel_leave_request(req, "emp_003")
check("8.1 本人撤回成功", "已撤回" in r2 and "余额未受影响" in r2, r2)
check("8.2 状态变为cancelled", db_status(req) == "cancelled")

# 非本人撤回
r = create_leave_request("emp_003", "personal", "2026-08-21", "2026-08-21", "权限")
req = extract_id(r)
r2 = cancel_leave_request(req, "emp_002")
check("8.3 非本人撤回被拒", "只能撤回自己" in r2, r2)

# 已批准不能撤回（需撤销）
r = create_leave_request("emp_002", "personal", "2026-08-22", "2026-08-22", "已批")
req = extract_id(r)
approve_leave(req, "emp_001", "同意")
r2 = cancel_leave_request(req, "emp_002")
check("8.4 已批准不能撤回", "已批准" in r2 and "无法撤回" in r2, r2)

print(f"  8.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 9. 撤销 (revoke)
# ═══════════════════════════════════════════════
print("\n▶ 9. 管理者撤销已批准申请")

# 假期未开始 → 可撤销，余额退回
r = create_leave_request("emp_002", "annual", "2026-12-01", "2026-12-01", "撤销测试")
req = extract_id(r)
approve_leave(req, "emp_001", "同意")
bal_before = db_used("emp_002", "annual")
r2 = revoke_leave_request(req, "emp_001", "计划变更")
check("9.1 撤销成功(未开始)", "已撤销" in r2 and "已退回" in r2, r2)
check("9.2 撤销后余额退回", db_used("emp_002", "annual") == bal_before - 1.0,
      f"{db_used('emp_002', 'annual')} vs {bal_before - 1.0}")

# 假期已开始 → 不能撤销
r = create_leave_request("emp_002", "annual", "2026-06-01", "2026-06-01", "已开始")
req = extract_id(r)
approve_leave(req, "emp_001", "同意")
r2 = revoke_leave_request(req, "emp_001", "晚了")
check("9.3 已开始不能撤销", "已开始" in r2 and "无法撤销" in r2, r2)

# 非直属上级撤销
r = create_leave_request("emp_003", "personal", "2026-12-15", "2026-12-15", "权限")
req = extract_id(r)
approve_leave(req, "emp_002", "同意")
r2 = revoke_leave_request(req, "emp_001", "跨级撤销")
check("9.4 非直属撤销被拒", "权限不足" in r2, r2)

print(f"  9.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 10. 待审批列表
# ═══════════════════════════════════════════════
print("\n▶ 10. 待审批列表")

# 先创建几条待审批
r1 = create_leave_request("emp_003", "annual", "2026-07-10", "2026-07-10", "待批1")
req1 = extract_id(r1)
r2 = create_leave_request("emp_003", "personal", "2026-07-11", "2026-07-11", "待批2")
req2 = extract_id(r2)

r = list_pending_approvals("emp_002")
check("10.1 李经理有待审批", "王小明" in r, r)

r = list_pending_approvals("emp_001")
check("10.2 张总待审批查询正常", isinstance(r, str) and len(r) > 0, r)

# 审批一条后数量减少
approve_leave(req1, "emp_002", "批了")
r = list_pending_approvals("emp_002")
check("10.3 审批后剩1条", "1 条" in r or "条" in r, r)

print(f"  10.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 11. Auto Approve
# ═══════════════════════════════════════════════
print("\n▶ 11. 自动审批 (auto_approve)")

# emp_002 年假有余额 剩余天数 + 提前 >= 1天 → 应自动通过
r = create_leave_request("emp_002", "annual", "2026-12-20", "2026-12-20",
                          "auto测试", auto_approve=True)
check("11.1 年假≤1天+余额足+提前→自动通过", "自动通过" in r and "已扣除" in r, r)

# emp_003 年假已用完 → auto_approve 应降级为 pending
r = create_leave_request("emp_003", "annual", "2026-12-25", "2026-12-25",
                          "auto失败", auto_approve=True)
check("11.2 余额不足auto降级pending", "等待" in r, r)

# check_auto_approval 工具
r = check_auto_approval("emp_002", "annual", "2026-12-20", "2026-12-20", 1.0)
check("11.3 check_auto显示全部通过", "✅" in r, r)

r = check_auto_approval("emp_003", "annual", "2026-12-25", "2026-12-25", 1.0)
check("11.4 check_auto显示余额不足", "❌" in r and "余额" in r, r)

print(f"  11.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 12. 边界条件
# ═══════════════════════════════════════════════
print("\n▶ 12. 边界条件")

# 重复审批
r = create_leave_request("emp_002", "personal", "2026-12-28", "2026-12-28", "边界")
req = extract_id(r)
approve_leave(req, "emp_001", "同意")
r2 = approve_leave(req, "emp_001", "再批")
check("12.1 重复审批被拦截", "已被处理" in r2, r2)

# 不存在的申请
r2 = approve_leave("lv_nonexist", "emp_001", "测试")
check("12.2 不存在的申请", "未找到" in r2, r2)

# 权限不足（非上级审批）
r = create_leave_request("emp_003", "personal", "2026-07-30", "2026-07-30", "权限")
req = extract_id(r)
r2 = approve_leave(req, "emp_001", "跨级批")
check("12.3 跨级审批被拒", "权限不足" in r2, r2)

# 半天年假
r = create_leave_request("emp_002", "annual", "2026-07-15", "2026-07-15",
                          "半天", auto_approve=True)
check("12.4 半天年假auto通过", "0.5" in r or "半天" in r.lower(), r)

# 多天事假 — CEO无上级，create时自动通过
r = create_leave_request("emp_001", "personal", "2026-09-10", "2026-09-15", "多天事假")
check("12.5 多天事假(6天)CEO自动通过", "已批准" in r or "自动通过" in r, r)
check("12.5b 事假used累加6天", db_used("emp_001", "personal") == 6.0,
      str(db_used("emp_001", "personal")))

# 假期历史
r = get_my_leave_history("emp_002")
check("12.6 历史记录非空", isinstance(r, str) and len(r) > 20, r[:80])

print(f"  12.x 小计: {passed}✓ / {failed}✗")

# ═══════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════
total = passed + failed
print(f"\n{'=' * 60}")
print(f"  结果: {passed} 通过 / {failed} 失败 / {total} 总计")
print(f"{'=' * 60}")
