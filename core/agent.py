"""Agent 主循环 —— DeepSeek 对话 + 工具调用。"""
import json
import os
from openai import OpenAI
from core.system_prompt import SYSTEM_PROMPT
from core.tool_registry import execute_tool
from tools.policy import TOOL_SEARCH_POLICY
from tools.leave import (
    TOOL_QUERY_LEAVE_BALANCE,
    TOOL_CREATE_LEAVE_REQUEST,
    TOOL_APPROVE_LEAVE,
    TOOL_REJECT_LEAVE,
    TOOL_LIST_PENDING_APPROVALS,
    TOOL_CANCEL_LEAVE_REQUEST,
    TOOL_REVOKE_LEAVE_REQUEST,
    TOOL_CHECK_AUTO_APPROVAL,
    TOOL_CHECK_DEPARTMENT_CONFLICT,
    TOOL_ADJUST_LEAVE_BALANCE,
)
from tools.employee import TOOL_GET_EMPLOYEE, TOOL_GET_MY_LEAVE_HISTORY, TOOL_SEARCH_EMPLOYEE
from tools.attendance import TOOL_QUERY_MY_ATTENDANCE, TOOL_GET_ATTENDANCE_STATS
from tools.dashboard import TOOL_CHECK_MY_DASHBOARD, TOOL_GET_COMPANY_DASHBOARD
from tools.overtime import (
    TOOL_SUBMIT_OVERTIME,
    TOOL_APPROVE_OVERTIME,
    TOOL_REJECT_OVERTIME,
    TOOL_QUERY_OVERTIME_BALANCE,
    TOOL_LIST_PENDING_OVERTIME,
)

# 根据 .env 配置 DeepSeek 客户端
_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        if not api_key:
            raise ValueError("请设置环境变量 DEEPSEEK_API_KEY")
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


TOOLS = [
    TOOL_SEARCH_POLICY,
    TOOL_QUERY_LEAVE_BALANCE,
    TOOL_CHECK_AUTO_APPROVAL,
    TOOL_CREATE_LEAVE_REQUEST,
    TOOL_APPROVE_LEAVE,
    TOOL_REJECT_LEAVE,
    TOOL_LIST_PENDING_APPROVALS,
    TOOL_GET_EMPLOYEE,
    TOOL_GET_MY_LEAVE_HISTORY,
    TOOL_SEARCH_EMPLOYEE,
    TOOL_CANCEL_LEAVE_REQUEST,
    TOOL_REVOKE_LEAVE_REQUEST,
    TOOL_QUERY_MY_ATTENDANCE,
    TOOL_GET_ATTENDANCE_STATS,
    TOOL_CHECK_MY_DASHBOARD,
    TOOL_GET_COMPANY_DASHBOARD,
    TOOL_CHECK_DEPARTMENT_CONFLICT,
    TOOL_SUBMIT_OVERTIME,
    TOOL_APPROVE_OVERTIME,
    TOOL_REJECT_OVERTIME,
    TOOL_QUERY_OVERTIME_BALANCE,
    TOOL_LIST_PENDING_OVERTIME,
    TOOL_ADJUST_LEAVE_BALANCE,
]

# 工具名 → Schema 映射，供按需路由使用
TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}

MAX_TOOL_ROUNDS = 5  # 防止无限循环


def _get_active_tools(user_message: str, employee_id: str) -> list[dict]:
    """根据路由模式返回本次对话应使用的工具列表。

    TOOL_ROUTING_MODE 可选值：
        - "all"     (默认): 全部 22 个工具，与原有行为一致
        - "keyword": 关键词匹配 + 角色分组，按需选择
    """
    mode = os.getenv("TOOL_ROUTING_MODE", "all")
    if mode == "keyword":
        from core.tool_planner import select_tools
        names = select_tools(user_message, employee_id)
        return [TOOLS_BY_NAME[n] for n in names if n in TOOLS_BY_NAME]
    return TOOLS


def chat(user_message: str, employee_id: str, history: list[dict]) -> str:
    """
    一次对话入口（非流式）。

    参数:
        user_message: 用户输入的自然语言
        employee_id:  当前登录员工的工号
        history:      对话历史列表（由调用方维护）

    返回:
        Agent 的文本回复
    """
    from datetime import datetime

    client = _get_client()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    current_date = datetime.now().strftime("%Y-%m-%d")

    history.append({"role": "user", "content": user_message})

    # 将 employee_id 注入 system prompt，让模型知道当前用户
    system_content = SYSTEM_PROMPT.format(
        current_employee_id=employee_id,
        current_date=current_date,
    )

    messages = [{"role": "system", "content": system_content}] + history

    # 滑动窗口：历史过长时裁剪旧消息，压缩为摘要
    from core.context_manager import trim_context, compact_history, COMPACT_TRIGGER
    messages = trim_context(messages)

    active_tools = _get_active_tools(user_message, employee_id)

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=active_tools,
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            # 追加 assistant 消息（含 tool_calls）
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
            })

            # 执行每个工具并追加结果
            for tc in msg.tool_calls:
                func_name = tc.function.name
                func_args = json.loads(tc.function.arguments)
                result = execute_tool(func_name, func_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            # 最终回复
            assistant_text = msg.content or ""
            history.append({"role": "assistant", "content": assistant_text})
            # 裁剪持久化历史，避免 DB 无限膨胀
            if len(history) > COMPACT_TRIGGER:
                history[:] = compact_history(history)
            return assistant_text

    return "抱歉，处理超时，请重新描述您的问题。"


# ── 工具名 → 中文显示名 ──
TOOL_DISPLAY_NAMES = {
    "search_policy": "检索公司制度文档",
    "query_leave_balance": "查询假期余额",
    "create_leave_request": "提交请假申请",
    "approve_leave": "审批请假",
    "reject_leave": "拒绝请假",
    "list_pending_approvals": "查看待审批列表",
    "get_employee": "查询员工信息",
    "get_my_leave_history": "查询请假历史",
    "search_employee": "搜索员工",
    "cancel_leave_request": "撤回请假申请",
    "revoke_leave_request": "撤销已批准请假",
    "query_my_attendance": "查询考勤记录",
    "get_attendance_stats": "查询考勤统计",
    "check_my_dashboard": "检查个人仪表盘",
    "get_company_dashboard": "查看公司全景仪表盘",
    "check_auto_approval": "检查自动审批条件",
    "check_department_conflict": "检查部门人力冲突",
    "submit_overtime": "提交加班记录",
    "approve_overtime": "审批加班记录",
    "reject_overtime": "拒绝加班记录",
    "query_overtime_balance": "查询调休余额",
    "list_pending_overtime": "查看待审批加班记录",
    "adjust_leave_balance": "调整员工假期余额",
}


def _tool_display_name(name: str) -> str:
    """返回工具的中文显示名。"""
    return TOOL_DISPLAY_NAMES.get(name, name)


def chat_stream(user_message: str, employee_id: str, history: list[dict]):
    """
    一次对话入口（流式）。生成器，逐条产出事件 dict。

    事件类型：
        {"type": "tool_call",  "tool": "check_my_dashboard"}
        {"type": "tool_result", "tool": "check_my_dashboard", "result_summary": "..."}
        {"type": "token", "text": "您"}
        {"type": "done"}

    参数同 chat()。
    """
    from datetime import datetime

    client = _get_client()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    current_date = datetime.now().strftime("%Y-%m-%d")

    history.append({"role": "user", "content": user_message})

    system_content = SYSTEM_PROMPT.format(
        current_employee_id=employee_id,
        current_date=current_date,
    )

    messages = [{"role": "system", "content": system_content}] + history

    # 滑动窗口：历史过长时裁剪旧消息，压缩为摘要
    from core.context_manager import trim_context, compact_history, COMPACT_TRIGGER
    messages = trim_context(messages)

    active_tools = _get_active_tools(user_message, employee_id)

    for _ in range(MAX_TOOL_ROUNDS):
        # ── 流式调用 DeepSeek ──
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=active_tools,
            stream=True,
        )

        # 累积本轮响应的 tool_calls 和 content
        tool_calls_map: dict[int, dict] = {}  # index → {id, name, arguments}
        content_parts: list[str] = []
        has_tool_calls = False

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # ── 处理 tool_calls delta ──
            if delta.tool_calls:
                has_tool_calls = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                    tc = tool_calls_map[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["arguments"] += tc_delta.function.arguments

            # ── 处理 content delta ──
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "token", "text": delta.content}

        # ── 如果本轮有 tool_calls，执行工具 ──
        if has_tool_calls and tool_calls_map:
            # 按 index 排序
            tool_calls = [tool_calls_map[i] for i in sorted(tool_calls_map.keys())]

            # 构建 assistant 消息
            messages.append({
                "role": "assistant",
                "content": "".join(content_parts) if content_parts else None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        }
                    }
                    for tc in tool_calls
                ]
            })

            for tc in tool_calls:
                func_name = tc["name"]
                display_name = _tool_display_name(func_name)

                # 通知前端：开始调用工具
                yield {"type": "tool_call", "tool": func_name, "display": display_name}

                try:
                    func_args = json.loads(tc["arguments"])
                    result = execute_tool(func_name, func_args)
                except Exception as e:
                    result = f"❌ 工具执行错误 ({func_name}): {str(e)}"

                # 通知前端：工具执行完毕
                yield {
                    "type": "tool_result",
                    "tool": func_name,
                    "display": display_name,
                    "result_summary": _summarize_result(result),
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
        else:
            # 本轮无 tool_calls —— 这是最终回复
            full_text = "".join(content_parts)
            history.append({"role": "assistant", "content": full_text})
            # 裁剪持久化历史，避免 DB 无限膨胀
            if len(history) > COMPACT_TRIGGER:
                history[:] = compact_history(history)
            yield {"type": "done"}
            return

    # 超出最大轮次
    yield {"type": "token", "text": "抱歉，处理超时，请重新描述您的问题。"}
    yield {"type": "done"}


def _summarize_result(result: str) -> str:
    """截取工具返回结果的前 80 字符作为摘要，给前端展示。"""
    if len(result) <= 80:
        return result
    return result[:80] + "…"
