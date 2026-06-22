# 工具按需路由优化方案

> 日期：2026-06-19  
> 状态：设计讨论阶段  
> 目标：解决每次 API 调用都发送全部 22 个工具定义导致的上下文膨胀问题

---

## 一、问题分析

### 当前状况

`core/agent.py` 每次调用 DeepSeek API 时，`tools=TOOLS` 参数携带全部 22 个工具的完整 JSON Schema：

```python
# core/agent.py 第 104 行
response = client.chat.completions.create(
    model=model,
    messages=messages,
    tools=TOOLS,   # ← 22 个完整 schema，每次约 6000 token
)
```

### 痛点

- 22 个工具 × 平均 ~300 token/个 ≈ **每次对话光工具定义就消耗 ~6000 token**
- 用户说"你好"或"谢谢"时，请假审批、加班管理等无关工具也照发不误
- 上下文窗口被工具定义占据，留给真正对话内容的空间更少
- API 调用成本与被塞入的无关工具成正比

---

## 二、三种候选方案

### 方案一：角色分组（最轻量）

**思路**：根据用户身份（普通员工 / 管理者）预先拆分工具列表。

```
EMPLOYEE_TOOLS  = 10 个（查余额、提交请假、查考勤...）
MANAGER_TOOLS   = 6 个（审批请假、拒绝请假、调整余额...）
```

**优点**：改动极小，无额外 API 调用，无准确度风险。  
**缺点**：同一角色内仍有无用工具（如用户只问考勤，请假工具仍会发过去）。  
**Token 节省**：~40-50%

### 方案二：关键词检索

**思路**：为每个工具配置关键词，根据用户消息匹配 Top-N 相关工具。

```python
TOOL_KEYWORDS = {
    "query_leave_balance":  ["请假", "年假", "假期", "余额"],
    "query_my_attendance":  ["打卡", "考勤", "迟到", "出勤"],
    ...
}
```

**优点**：比角色分组更精准。  
**缺点**：关键词维护成本高，同义词/口语化表达容易漏匹配。  
**Token 节省**：~60-70%

### 方案三：两阶段调用（最精准，本文重点）

**思路**：第一轮不带工具，让模型说出需要哪些工具；第二轮只带选中的工具。

```
第 1 轮：无 tools 参数，只发轻量工具目录（~500 token）
         → 模型输出：["query_leave_balance", "create_leave_request"]

第 2 轮：tools = [选中的 3 个]（~900 token）
         → 正常 ReAct 循环
```

**优点**：最精准，token 节省最大（~70-80%）。  
**缺点**：多一次 API 调用（多一次网络延迟），模型可能"点错菜"。

---

## 三、方案三详细设计

### 3.1 架构概览

```
原方案（一次调用）：
┌──────────────────────────────────────────────────────┐
│  API 调用（1 次）                                     │
│  tools = [22 个完整 JSON Schema]     ~6000 token      │
│  → 模型输出 tool_calls 或最终回复     ~1000 token      │
│  总计：~7000 token / 次                               │
└──────────────────────────────────────────────────────┘

两阶段方案：
┌─────────────────────────┐  ┌─────────────────────────┐
│  第一阶段（规划）         │  │  第二阶段（执行）         │
│  无 tools 参数           │  │  tools = [选中的 N 个]    │
│  只发工具目录文本 ~500t   │  │  ~300×N token           │
│  → 返回工具名列表 ~50t    │  │  → 正常 ReAct 循环       │
│  合计：~550 token        │  │  合计：~1500 token       │
└─────────────────────────┘  └─────────────────────────┘
  总计：~2050 token / 次（节省 ~70%）
```

### 3.2 "加载工具"的本质

工具 Schema 在程序启动时已全部导入内存（`tools/*.py` 中的 `TOOL_*` 字典），"按需加载"不是从磁盘读文件，而是：

```python
# 全局工具总目录（内存中的字典，启动时就建好）
ALL_TOOLS_MAP = {
    "query_leave_balance":  TOOL_QUERY_LEAVE_BALANCE,   # dict 对象
    "approve_leave":        TOOL_APPROVE_LEAVE,         # dict 对象
    # ... 全部 22 个，已在内存中
}

# "加载"就是字典取值 + 列表拼接
selected_tools = [ALL_TOOLS_MAP[name] for name in tool_names]
#                ↑ O(1) 操作，极快，不碰磁盘
```

### 3.3 第一阶段实现（规划阶段）

```python
# ── 轻量工具目录（仅工具名 + 一句话描述，500 token 以内）──
TOOL_CATALOG = """
可用工具列表：
1. query_leave_balance      — 查询假期余额
2. create_leave_request     — 提交请假申请
3. approve_leave            — 审批通过请假（管理者）
4. reject_leave             — 拒绝请假（管理者）
5. list_pending_approvals   — 查看待审批列表（管理者）
6. cancel_leave_request     — 撤回请假申请
7. revoke_leave_request     — 撤销已批准请假（管理者）
8. check_auto_approval      — 检查是否符合自动审批条件
9. check_department_conflict— 检查部门人力冲突
10. search_policy           — 检索公司制度文档
11. get_employee            — 查询员工信息
12. get_my_leave_history    — 查询请假历史
13. search_employee         — 搜索员工
14. query_my_attendance     — 查询考勤记录
15. get_attendance_stats    — 查询考勤统计
16. check_my_dashboard      — 查看个人仪表盘
17. get_company_dashboard   — 查看公司全景仪表盘（管理者）
18. submit_overtime         — 提交加班记录
19. approve_overtime        — 审批加班（管理者）
20. reject_overtime         — 拒绝加班（管理者）
21. query_overtime_balance  — 查询调休余额
22. list_pending_overtime   — 查看待审批加班（管理者）
23. adjust_leave_balance    — 调整员工假期余额（管理者）
"""


def _plan_tools(user_message: str, employee_id: str) -> list[str]:
    """
    第一阶段：让模型根据用户消息选择需要的工具。
    返回工具名列表，如 ["query_leave_balance", "check_auto_approval"]。
    """
    client = _get_client()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    plan_messages = [
        {
            "role": "system",
            "content": f"""你是 HR 助手的任务规划模块。你不需要直接回答用户问题，
只负责判断需要哪些工具。

{TOOL_CATALOG}

规则：
1. 只选确实需要的工具，宁少勿多
2. 返回 JSON 数组格式，如：["query_leave_balance", "search_policy"]
3. 如果用户的问候或闲聊不需要任何工具，返回空数组：[]
4. 不要返回任何其他文字，只返回 JSON 数组
5. "get_employee" 和 "search_policy" 是兜底工具，不确定时可选上

当前用户工号：{employee_id}"""
        },
        {"role": "user", "content": user_message},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=plan_messages,
        # 注意：无 tools 参数！模型纯文本输出
        temperature=0.1,   # 低温度，确保稳定输出
    )

    raw = response.choices[0].message.content.strip()

    # 提取 JSON 数组
    try:
        tool_names = json.loads(raw)
        if not isinstance(tool_names, list):
            tool_names = []
    except json.JSONDecodeError:
        # 降级：返回全部工具
        tool_names = list(ALL_TOOLS_MAP.keys())

    return tool_names
```

### 3.4 第二阶段实现（执行阶段，复用现有逻辑）

第二阶段完全复用现有的 `chat()` 或 `chat_stream()` 逻辑，**唯一区别是 `tools=` 参数不再是全部的 22 个**：

```python
def chat_two_phase(user_message: str, employee_id: str, history: list) -> str:
    """两阶段对话入口（非流式）。"""

    # ── 第一阶段：规划 ──
    tool_names = _plan_tools(user_message, employee_id)

    # ── 兜底策略：始终包含基础工具 ──
    for name in ["get_employee", "search_policy"]:
        if name not in tool_names:
            tool_names.append(name)

    # ── "加载"选中工具的完整 Schema ──
    selected_tools = [ALL_TOOLS_MAP[name] for name in tool_names if name in ALL_TOOLS_MAP]

    # ── 第二阶段：正常 ReAct 循环（与现有 chat() 逻辑一致）──
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

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=selected_tools,   # ← 只发选中的，不是全部！
        )
        msg = response.choices[0].message

        if msg.tool_calls:
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
            assistant_text = msg.content or ""
            history.append({"role": "assistant", "content": assistant_text})
            return assistant_text

    return "抱歉，处理超时，请重新描述您的问题。"
```

### 3.5 容错与降级策略

| 场景 | 处理方式 |
|------|---------|
| 第一阶段返回的 JSON 解析失败 | 降级为全部工具 |
| 第一阶段返回空数组 `[]`（问候/闲聊） | 直接调用模型，无工具 |
| 第一阶段漏选了必需工具 | 第二阶段会触发"兜底工具"（get_employee, search_policy） |
| 第二阶段工具不足，模型回答"我做不到" | 可降级为带全部工具重试（可选） |

```python
# 可选：降级重试逻辑
def chat_with_fallback(user_message, employee_id, history):
    reply = chat_two_phase(user_message, employee_id, history)

    # 如果模型回复暗示能力不足，带全部工具重试
    FALLBACK_SIGNALS = ["抱歉", "无法", "做不到", "不支持", "没有权限"]
    if any(signal in reply for signal in FALLBACK_SIGNALS):
        # 重试：带着全部工具
        return chat(user_message, employee_id, history)  # 现有函数

    return reply
```

---

## 四、前端交互设计：方案 A（可见模式）

### 推荐方案：向用户展示工具选择过程

企业 HR 应用需要建立信任，用户看到 AI 的"思考过程"会更放心。

### 新增 SSE 事件类型

在现有事件类型基础上扩展：

```python
# 现有事件（core/agent.py 第 188-190 行）
# {"type": "tool_call",  ...}     — 工具调用中
# {"type": "tool_result", ...}     — 工具执行完成
# {"type": "token", ...}           — 逐字输出回复
# {"type": "done"}                 — 结束

# 新增事件
# {"type": "planning", "tools": ["query_leave_balance", ...]}  — 第一阶段结果
```

### 流式两阶段实现

```python
def chat_stream_two_phase(user_message: str, employee_id: str, history: list):
    """两阶段流式对话。"""

    # ── 第一阶段：规划（可展示给前端）──
    tool_names = _plan_tools(user_message, employee_id)

    # 兜底
    for name in ["get_employee", "search_policy"]:
        if name not in tool_names:
            tool_names.append(name)

    # 通知前端规划结果
    yield {
        "type": "planning",
        "tools": tool_names,
        "display": [TOOL_DISPLAY_NAMES.get(n, n) for n in tool_names],
    }

    selected_tools = [ALL_TOOLS_MAP[name] for name in tool_names if name in ALL_TOOLS_MAP]

    # ── 第二阶段：正常流式 ReAct（复用 chat_stream 后半段逻辑）──
    # ... 与现有 chat_stream() 一致，仅 tools=selected_tools 不同
```

### 前端效果示意

```
┌─────────────────────────────────────────────┐
│  👤 用户：帮我看年假还剩几天，够的话请一天    │
│                                             │
│  🔄 AI 正在规划...                           │
│     ↳ 需查询：假期余额 · 自动审批条件 ·       │
│       创建请假申请                            │
│                                             │
│  🔧 正在查询假期余额...                      │
│  ✅ 年假：剩余 3 天                          │
│                                             │
│  🔧 正在检查自动审批条件...                   │
│  ✅ 符合自动审批条件                          │
│                                             │
│  🔧 正在提交请假申请...                      │
│  ✅ 已自动通过（编号 lv_abc123）              │
│                                             │
│  🤖 AI：好的，已为您提交 1 天年假申请         │
│      （2026-06-20），系统自动审批通过，       │
│      年假余额已扣除，剩余 2 天。              │
└─────────────────────────────────────────────┘
```

---

## 五、实施约束（重要）

### 不可做的事

1. **不可大改 `core/agent.py` 的现有结构** — 现有的 `chat()` 和 `chat_stream()` 函数签名和返回格式保持不变
2. **不可修改现有工具函数** — `tools/*.py` 中已实现的工具函数不动
3. **不可修改 `core/tool_registry.py` 的分发逻辑** — `execute_tool()` 函数保持不变
4. **不可破坏现有的 `POST /api/chat` 和 `POST /api/chat/stream` 接口契约** — `ChatRequest` 和 `ChatResponse` 的字段不变
5. **不可影响飞书回调等既有功能**

### 必须做的事

1. **新增代码放在独立模块** — 规划逻辑放在 `core/tool_planner.py`，不混入 `core/agent.py`
2. **通过配置开关控制** — 提供环境变量 `TOOL_ROUTING_MODE`（可选值 `all` / `role` / `keyword` / `two-phase`），默认 `all`（兼容现有行为）
3. **向后兼容** — 默认行为与现在完全一致，新方案通过配置启用
4. **新增事件类型兼容前端** — 前端应能优雅忽略不认识的 `type` 字段

### 推荐的新增文件结构

```
core/
├── agent.py              ← 不动（或仅加配置读取 + 新分支调用）
├── tool_planner.py        ← 新增：第一阶段规划逻辑
├── tool_registry.py       ← 不动
└── system_prompt.py       ← 不动
```

### 配置示例（`.env`）

```bash
# 工具路由模式：all | role | keyword | two-phase
TOOL_ROUTING_MODE=two-phase
```

---

## 六、方案对比总结

| 维度 | 方案一（角色） | 方案二（关键词） | 方案三（两阶段） |
|------|-------------|---------------|----------------|
| Token 节省 | ~40-50% | ~60-70% | ~70-80% |
| 额外 API 调用 | 0 | 0 | 1 |
| 额外延迟 | 无 | 无 | +0.5~2s |
| 准确度风险 | 无 | 低 | 中（可降级兜底） |
| 实现复杂度 | ⭐ | ⭐⭐ | ⭐⭐⭐ |
| 维护成本 | 低 | 中（关键词需维护） | 低 |
| 推荐场景 | 快速优化 | 工具 30+ 时 | 成本敏感 / 工具 50+ 时 |

**当前阶段建议**：先实施方案一（角色分组）作为快速优化，验证效果后按需迭代到方案三。

---

## 七、相关文件索引

| 文件 | 职责 | 是否需修改 |
|------|------|-----------|
| `core/agent.py` | Agent 主循环、工具列表定义 | 是（加配置分支） |
| `core/tool_registry.py` | 工具分发 | 否 |
| `core/system_prompt.py` | 系统提示词 | 可能（轻量目录可放在此） |
| `tools/*.py` | 工具定义 + 实现 | 否 |
| `api.py` | FastAPI 接口 | 否 |
| `.env` | 配置 | 是（加开关） |
