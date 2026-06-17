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
)
from tools.employee import TOOL_GET_EMPLOYEE, TOOL_GET_MY_LEAVE_HISTORY

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
    TOOL_CREATE_LEAVE_REQUEST,
    TOOL_APPROVE_LEAVE,
    TOOL_REJECT_LEAVE,
    TOOL_LIST_PENDING_APPROVALS,
    TOOL_GET_EMPLOYEE,
    TOOL_GET_MY_LEAVE_HISTORY,
]

MAX_TOOL_ROUNDS = 5  # 防止无限循环


def chat(user_message: str, employee_id: str, history: list[dict]) -> str:
    """
    一次对话入口。

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

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
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
            return assistant_text

    return "抱歉，处理超时，请重新描述您的问题。"
