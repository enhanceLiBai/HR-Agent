"""工具按需路由 —— 方案二：关键词匹配 + 角色分组。

策略：
  1. 关键词匹配用户意图 → 选出相关工具
  2. 叠加角色分组（管理者多带管理工具）
  3. 始终包含基础工具（get_employee, search_policy）
  4. 意图为请假/加班时，自动追加关联的工作流工具
  5. 匹配不到任何工具 → 回退到角色分组兜底
"""
import os
from sqlalchemy import text
from db.database import get_session

# ── 关键词 → 工具映射 ──
# 企业 HR 场景输入高度模式化，关键词覆盖核心话术即可
TOOL_KEYWORDS: dict[str, list[str]] = {
    # ── 员工常用工具 ──
    "query_leave_balance":    ["余额", "还剩", "还有", "剩几天", "额度", "剩多少", "够不够"],
    "create_leave_request":   ["请假", "请年假", "请事假", "请病假",
                               "请婚假", "请丧假", "请产假", "陪产假", "调休假",
                               "想请", "要请", "帮我请", "调休请假"],
    "query_my_attendance":    ["考勤", "打卡", "出勤", "签到"],
    "get_attendance_stats":   ["考勤统计", "统计", "迟到", "全勤", "早退", "缺勤", "旷工"],
    "submit_overtime":        ["加班", "OT", "ot"],
    "query_overtime_balance": ["调休余额", "调休还剩", "加班余额", "调休时长", "调休查询"],
    "get_my_leave_history":   ["请假记录", "请假历史", "历史", "之前请", "过去请"],
    "cancel_leave_request":   ["撤回", "取消申请", "不请了"],
    "search_employee":        ["搜索员工", "找员工", "查员工", "查一下", "搜一下", "哪个员工"],
    "check_my_dashboard":     ["仪表盘", "概览", "提醒", "汇总"],
    # ── 管理者工具 ──
    "list_pending_approvals": ["待审批", "审批列表", "有哪些审批", "查看审批"],
    "approve_leave":          ["批准", "通过", "同意请假"],
    "reject_leave":           ["拒绝", "驳回", "不批"],
    "revoke_leave_request":   ["撤销"],
    "approve_overtime":       ["批准加班", "通过加班"],
    "reject_overtime":        ["拒绝加班", "驳回加班"],
    "list_pending_overtime":  ["待审批加班", "加班审批"],
    "get_company_dashboard":  ["公司全景", "全公司", "部门情况", "公司情况"],
    "adjust_leave_balance":   ["调整余额", "修改额度", "加额度", "扣额度", "调整额度"],
}

# ── 基础工具（任何对话都带上，兜底用）──
BASE_TOOLS = ["get_employee", "search_policy"]


def select_tools(user_message: str, employee_id: str) -> list[str]:
    """
    根据用户消息关键词 + 角色，返回本次应发送的工具名列表。

    参数:
        user_message: 用户输入的自然语言
        employee_id:  当前员工工号（用于判断是否为管理者）

    返回:
        工具名列表，如 ["get_employee", "search_policy", "query_leave_balance", ...]
    """
    is_manager = _check_is_manager(employee_id)
    matched: set[str] = set()

    # ── 1. 关键词匹配 ──
    for tool_name, keywords in TOOL_KEYWORDS.items():
        for kw in keywords:
            if kw in user_message:
                matched.add(tool_name)
                break

    # ── 2. 意图推断，自动追加关联工具 ──
    leave_keywords = ["请假", "请年假", "请事假", "请病假",
                      "请婚假", "请丧假", "请产假", "陪产假", "调休假",
                      "想请", "要请", "调休请假", "帮我请"]
    overtime_keywords = ["加班", "OT", "ot"]
    attendance_keywords = ["考勤", "打卡", "出勤", "迟到", "全勤", "早退", "缺勤", "旷工"]
    policy_keywords = ["制度", "规定", "政策", "怎么", "如何", "什么条件", "规则", "能请几天"]

    leave_intent = any(kw in user_message for kw in leave_keywords)
    overtime_intent = any(kw in user_message for kw in overtime_keywords)
    attendance_intent = any(kw in user_message for kw in attendance_keywords)
    policy_intent = any(kw in user_message for kw in policy_keywords)

    if leave_intent:
        matched.add("search_policy")
        matched.add("query_leave_balance")
        matched.add("check_auto_approval")
        matched.add("check_department_conflict")
        if "调休" in user_message:
            matched.add("query_overtime_balance")

    if overtime_intent:
        matched.add("search_policy")
        matched.add("query_overtime_balance")

    if attendance_intent:
        matched.add("get_attendance_stats")

    if policy_intent:
        matched.add("search_policy")

    # ── 2.5 排他修正：加班意图且无请假意图时，清除误匹配的请假工具 ──
    if overtime_intent and not leave_intent:
        matched.discard("create_leave_request")
        matched.discard("query_leave_balance")
        matched.discard("check_auto_approval")
        matched.discard("check_department_conflict")

    # ── 3. 管理者专属工具 ──
    if is_manager:
        matched.update({
            "list_pending_approvals", "approve_leave", "reject_leave",
            "revoke_leave_request", "approve_overtime", "reject_overtime",
            "list_pending_overtime", "get_company_dashboard", "adjust_leave_balance",
        })

    # ── 4. 始终包含基础工具 ──
    matched.update(BASE_TOOLS)

    # ── 5. 兜底：如果只匹配到基础工具（用户意图完全没命中），按消息长度决定策略 ──
    if matched == set(BASE_TOOLS):
        # 短消息（≤5 字）视为问候/闲聊，只用基础工具
        if len(user_message) <= 5:
            pass  # matched 保持 BASE_TOOLS，不再追加
        else:
            # 较长消息没命中关键词 → 回退到角色分组兜底
            matched.update(_get_role_tools(is_manager))

    return list(matched)


# ── 内部辅助 ──

def _check_is_manager(employee_id: str) -> bool:
    """查数据库判断该员工是否有下属。"""
    session = get_session()
    try:
        count = session.execute(
            text("SELECT COUNT(*) FROM employees WHERE manager_id = :id"),
            {"id": employee_id},
        ).scalar()
        return count > 0
    except Exception:
        return False
    finally:
        session.close()


def _get_role_tools(is_manager: bool) -> set[str]:
    """回退方案：按角色返回常用工具集（方案一的逻辑作为兜底）。"""
    employee_tools = {
        "query_leave_balance",
        "create_leave_request",
        "get_my_leave_history",
        "cancel_leave_request",
        "query_my_attendance",
        "get_attendance_stats",
        "check_my_dashboard",
        "submit_overtime",
        "query_overtime_balance",
        "search_employee",
        "check_auto_approval",
        "check_department_conflict",
    }

    if is_manager:
        employee_tools.update({
            "list_pending_approvals",
            "approve_leave",
            "reject_leave",
            "revoke_leave_request",
            "approve_overtime",
            "reject_overtime",
            "list_pending_overtime",
            "get_company_dashboard",
            "adjust_leave_balance",
        })

    return employee_tools
