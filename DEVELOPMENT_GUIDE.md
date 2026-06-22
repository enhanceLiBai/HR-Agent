# HR Agent 开发指导文档

> 本文档锁定系统架构、技术选型、功能规格。Claude Code 按此规格逐项构建。

---

## 一、项目定位

飞书 HR 智能助手。员工在飞书中**单聊机器人**，用自然语言完成请假、查考勤、提交加班等 HR 事务。管理者通过**卡片消息**一键审批。

两个交互入口：
- **飞书机器人**（主力）：单聊，处理所有 HR 事务
- **Web 前端**（辅助）：`static/` 下的页面，保留兼容

---

## 二、技术栈（已锁定）

| 项 | 选型 | 说明 |
|---|------|------|
| 对话模型 | `deepseek-v4-flash` | OpenAI 兼容 API |
| 向量模型 | 智谱 `embedding-2` | 1024 维 |
| 向量存储 | `faiss-cpu` | 本地文件 |
| 数据库 | SQLite | 本地 `hr.db` |
| DB 驱动 | SQLAlchemy | 仅连接管理 + 原生 SQL |
| Web 框架 | FastAPI | 对接飞书 Webhook + 前端 API |
| 飞书 SDK | `lark-oapi` | 飞书开放平台官方 Python SDK |
| 语言 | Python 3.11+ | — |
| 核心原则 | 零 Agent 框架 | 不用 LangChain，纯手写 |

---

## 三、依赖清单

```txt
openai>=1.0.0
faiss-cpu>=1.7.4
sqlalchemy>=2.0.0
pymupdf>=1.23.0
python-dotenv>=1.0.0
numpy>=1.24.0
fastapi>=0.100.0
uvicorn>=0.23.0
lark-oapi>=1.0.0
```

---

## 四、项目文件结构

```
hr-agent/
├── .env
├── .env.example
├── requirements.txt
├── policies.md                  # 公司制度（RAG 知识源）
├── api.py                       # FastAPI 入口（含飞书 Webhook 路由）
│
├── core/
│   ├── __init__.py
│   ├── agent.py                 # Agent 主循环（非流式 + 流式）
│   ├── tool_registry.py         # 工具分发
│   └── system_prompt.py         # System Prompt
│
├── tools/
│   ├── __init__.py
│   ├── policy.py                # search_policy — RAG 检索
│   ├── leave.py                 # 请假：查余额/提交/审批/撤回/撤销/调整
│   ├── employee.py              # 员工信息查询
│   ├── attendance.py            # 考勤：打卡记录/统计
│   ├── dashboard.py             # 仪表盘：个人/管理者/公司全景
│   └── overtime.py              # 加班：提交/审批/查余额
│
├── feishu/                      # 🆕 飞书接入层
│   ├── __init__.py
│   ├── webhook.py               # 消息/卡片/事件回调路由
│   ├── auth.py                  # 飞书 Token 管理 + 验签
│   ├── identity.py              # open_id ↔ employee_id 绑定映射
│   ├── adapter.py               # 飞书消息 ↔ Agent 消息格式转换
│   └── card.py                  # 审批卡片构建与发送
│
├── rag/
│   ├── __init__.py
│   ├── loader.py
│   ├── embedder.py
│   └── retriever.py
│
├── db/
│   ├── __init__.py
│   ├── database.py
│   ├── models.py                # 建表（含 feishu_open_id）
│   └── init_db.py               # 种子数据
│
├── static/                      # Web 前端（保留）
└── test_tools.py
```

---

## 五、数据库设计

### 5.1 employees 表（变更）

```sql
-- 新增 feishu_open_id 字段（可选，员工自行绑定时填入）
ALTER TABLE employees ADD COLUMN feishu_open_id TEXT;
```

飞书用户通过 `open_id` 标识。该字段为 NULL 时表示未绑定，员工首次使用时通过对话绑定。

### 5.2 飞书会话表（新增）

```sql
-- 飞书单聊会话状态。按飞书 chat_id 隔离，服务重启不丢失。
CREATE TABLE IF NOT EXISTS feishu_sessions (
    chat_id         TEXT PRIMARY KEY,       -- 飞书会话 ID
    employee_id     TEXT NOT NULL,          -- 绑定的员工工号
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
```

Agent 对话历史仍存内存（`core/agent.py` 的 `history` 参数），`feishu_sessions` 只存绑定关系。如需持久化对话历史，后续再加。

### 5.3 其余表不变

`leave_balances`、`leave_requests`、`attendance_records`、`overtime_records`、`leave_balance_adjustments` 结构不变。

---

## 六、异步处理方案

### 6.1 为什么需要异步

飞书 Webhook 回调有 **3 秒超时**：收到请求后必须在 3 秒内返回 HTTP 200，否则飞书认为失败并重试（最多 3 次）。

Agent 一次对话耗时远超 3 秒（请假流程 6 次 LLM 调用，约 10-20 秒），因此必须：

> 收到请求 → 立刻返回 200 → 后台线程处理 Agent 对话

### 6.2 方案：FastAPI BackgroundTasks

FastAPI 自带 `BackgroundTasks`，无需 `async/await`，无需改现有代码：

```python
# api.py
from fastapi import BackgroundTasks

@app.post("/feishu/webhook")
def feishu_webhook(request: dict, background_tasks: BackgroundTasks):
    # 1. 验签
    # 2. 立刻返回 200
    # 3. Agent 处理丢到后台线程池
    background_tasks.add_task(process_feishu_message, request)
    return {"code": 0}

def process_feishu_message(request: dict):
    # 同步函数，线程池里跑（默认 40 线程）
    # 多人同时发消息，各跑各的线程，互不等
    ...
```

**并发能力**：Agent 大部分时间在等 I/O（DeepSeek API），等待时 Python 释放 GIL，其他线程可以跑。10 人以内完全没问题。

### 6.3 SQLite 并发写入

SQLite 默认只允许一个线程同时写入。多人同时写时会报 `database is locked`。

解决：连接串加 `timeout`，写锁冲突时等待而非报错：

```python
# db/database.py
engine = create_engine(
    "sqlite:///hr.db",
    connect_args={
        "check_same_thread": False,
        "timeout": 10  # 写锁等待 10 秒
    }
)
```

---

## 七、飞书接入层设计

### 7.1 整体数据流

```
飞书用户发消息
     │
     ▼
飞书服务器 ──HTTP POST──→ /feishu/webhook
                              │
                    ┌─────────▼──────────┐
                    │ auth.py: 验签       │
                    │ (防伪造请求)         │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ identity.py: 身份映射│
                    │ chat_id → employee_id│
                    │ (未绑定→引导绑定)     │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ adapter.py: 消息转换 │
                    │ 飞书文本 → Agent输入  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ core/agent.py       │
                    │ chat_stream()       │
                    └─────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼                               ▼
       普通文本回复                      需要发审批卡片
              │                               │
              ▼                               ▼
      adapter 转回飞书格式              card.py 构建卡片
      发回飞书消息 API                发给审批人飞书消息
```

### 7.2 身份绑定流程

```
【首次使用 — 未绑定】
用户: "你好"
机器人: "你好！我是 HR 助手。请先绑定您的员工信息。
        请输入您的员工工号，例如：emp_003"
用户: "emp_003"
机器人: (查询 employees 表，找到 王小明)
        "您是技术部的王小明，对吗？请回复'是'确认绑定。"
用户: "是"
机器人: (将 feishu_open_id 写入 employees 表，写入 feishu_sessions)
        "绑定成功！你好王小明，有什么可以帮你的？"

【再次使用 — 已绑定】
用户: "我还有多少年假"
机器人: (查到绑定关系 → 直接调用 Agent)
        → Agent 执行 query_leave_balance → 返回结果
```

### 7.3 绑定验证规则

- 输入的工号必须存在于 `employees` 表
- 输入工号后，系统报出姓名+部门，需用户确认（"是"/"对"/"确认"）
- 一个 `feishu_open_id` 只能绑定一个员工
- 一个员工可以被多个飞书账号绑定？（暂不允许：一个工号只能绑一个 open_id，后来的覆盖前一个）
- 绑定后 `feishu_sessions` 写入记录，后续请求直接查表获取 `employee_id`

### 7.4 消息适配层

Agent 核心目前接收三个参数：`user_message`, `employee_id`, `history`。飞书接入时：

- `employee_id`：从 `feishu_sessions` 查表获取
- `history`：内存 dict，key 为 `chat_id`（飞书对话 ID，天然隔离）
- `user_message`：飞书消息的文本内容

```
adapter.py 职责：

1. 入站：飞书消息 JSON → user_message (str)
   - 提取 msg_type = text 的文本内容
   - 其他类型（图片/文件）→ 回复 "暂不支持此类消息"

2. 出站：Agent 回复文本 → 飞书消息 API 调用
   - 调用飞书 "发送消息" API
   - 内容过长时分条发送

3. 出站：审批通知 → 飞书卡片消息
   - 调用 card.py 构建卡片
   - 通过飞书 "发送消息" API 发给审批人
```

### 7.5 卡片消息设计

请假申请提交后，发给审批人的卡片：

```json
{
  "header": {
    "title": {"tag": "plain_text", "content": "📋 待审批：请假申请"}
  },
  "elements": [
    {"tag": "div", "text": {"tag": "lark_md", "content": "**申请人：**王小明"}},
    {"tag": "div", "text": {"tag": "lark_md", "content": "**类型：**年假"}},
    {"tag": "div", "text": {"tag": "lark_md", "content": "**日期：**2026-06-20 至 2026-06-22"}},
    {"tag": "div", "text": {"tag": "lark_md", "content": "**天数：**3 天"}},
    {"tag": "div", "text": {"tag": "lark_md", "content": "**原因：**回家探亲"}},
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {
          "tag": "button",
          "text": {"tag": "plain_text", "content": "✅ 批准"},
          "type": "primary",
          "value": "{\"action\":\"approve\",\"request_id\":\"lv_xxx\"}"
        },
        {
          "tag": "button",
          "text": {"tag": "plain_text", "content": "❌ 拒绝"},
          "type": "danger",
          "value": "{\"action\":\"reject\",\"request_id\":\"lv_xxx\"}"
        }
      ]
    }
  ]
}
```

按钮点击后，飞书回调到 `/feishu/webhook`，携带 `action` 和 `request_id`。系统执行对应的 `approve_leave` 或弹出拒绝原因输入。

### 7.6 工具函数的飞书副作用

审批相关工具在执行数据库操作的同时，直接调用飞书 API 发送卡片或消息。这样做的好处是简单直接，Agent 层无感知。

会触发飞书副作用只有 4 个工具：

| 工具 | 数据库操作 | 飞书副作用 |
|------|-----------|-----------|
| `create_leave_request` | INSERT leave_requests (pending) | 给审批人发卡片 |
| `submit_overtime` | INSERT overtime_records (pending) | 给审批人发卡片 |
| `approve_leave` | UPDATE status='approved'，扣余额 | 更新卡片为"已批准" + 通知申请人 |
| `reject_leave` | UPDATE status='rejected' | 更新卡片为"已拒绝" + 通知申请人 |

```python
# 示例：create_leave_request 内部
def create_leave_request(employee_id, leave_type, start_date, end_date, reason, auto_approve=False):
    # 1. 数据库操作（现有逻辑）
    request_id = "lv_" + secrets.token_hex(4)
    # INSERT INTO leave_requests ...

    # 2. 🆕 如果需要人工审批 → 发卡片
    if status == "pending":
        from feishu.card import send_approval_card
        approver_open_id = _get_approver_feishu_open_id(employee_id)
        if approver_open_id:
            send_approval_card(approver_open_id, request_id, ...)

    # 3. 返回文本给 Agent（现有逻辑）
    return "✅ 请假申请已提交..."
```

### 7.7 卡片按钮回调处理

卡片按钮点击后，飞书回调到 `/feishu/webhook`，携带 `action` 和 `request_id`。

```
李经理点 [✅ 批准]
     │
     ▼
飞书回调 → /feishu/webhook
     │
     ├─ execute_tool("approve_leave", request_id, approver_id)
     │   └─ DB: status 'pending' → 'approved'，余额扣除
     │   └─ 待办自动消失（list_pending_approvals 查不到了）
     │
     ├─ 更新李经理的卡片：按钮变灰 → "✅ 已批准"
     │
     └─ 给王小明发消息："你的请假 lv_xxx 已批准"

李经理点 [❌ 拒绝]
     │
     ▼
飞书弹出输入框 → 审批人填拒绝原因
     │
     ├─ execute_tool("reject_leave", request_id, approver_id, reason)
     │   └─ DB: status 'pending' → 'rejected'，不扣余额
     │
     ├─ 更新卡片 → "❌ 已拒绝"
     │
     └─ 给王小明发消息："你的请假 lv_xxx 已被拒绝，原因：..."
```

卡片状态变化视觉效果：

```
┌──────────────────────┐        ┌──────────────────────┐
│ 📋 待审批：请假申请    │        │ 📋 待审批：请假申请    │
│ 申请人：王小明         │   →    │ 申请人：王小明         │
│ 日期：6/20-6/22       │        │ 日期：6/20-6/22       │
│ [✅ 批准] [❌ 拒绝]   │        │ ✅ 已批准             │
└──────────────────────┘        └──────────────────────┘
```

关键：**不需要"删除待办事务"**。待办是 `WHERE status='pending'` 实时查出来的，status 一变就自动消失。

---

## 八、飞书开放平台配置

### 8.1 需要获取的凭证

| 配置项 | 说明 |
|--------|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |
| `FEISHU_VERIFICATION_TOKEN` | 事件订阅验签 Token |
| `FEISHU_ENCRYPT_KEY` | 消息加密 Key（可选） |

### 8.2 需要配置的能力

在飞书开放平台后台开启：

1. **机器人能力**：接收/发送单聊消息
2. **事件订阅**：
   - `im.message.receive_v1`（接收消息）
   - `im.message.action.trigger`（卡片按钮回调）
3. **权限**：
   - `im:message:send`（发送消息）
   - `im:message:read`（读取消息）

### 8.3 环境变量

```bash
# 原有
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash
ZHIPU_API_KEY=xxx
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ZHIPU_EMBEDDING_MODEL=embedding-2

# 🆕 飞书
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
```

---

## 九、需要改动的现有文件

| 文件 | 改动 |
|------|------|
| `db/models.py` | employees 表加 `feishu_open_id` 字段；新建 `feishu_sessions` 表 |
| `db/init_db.py` | 建表语句更新 |
| `api.py` | 新增 `/feishu/webhook` 路由；加上飞书 Token 管理 |
| `requirements.txt` | 加 `lark-oapi` |
| `core/agent.py` | **不动** |
| `core/system_prompt.py` | **不动** |
| `core/tool_registry.py` | **不动** |
| `tools/*.py` | **不动** |

---

## 十、关键设计决策（已确定）

1. **单聊模式**：员工与机器人一对一私聊，保护隐私
2. **A+B 混合绑定**：表里有 `feishu_open_id` 字段，但员工首次自己绑定，永久生效
3. **卡片消息审批**：请假/加班提交后，发卡片给审批人，按钮一键审批
4. **简洁验证**：绑定只需工号+确认姓名，不做手机号验证（学生项目阶段）
5. **会话隔离**：按飞书 `chat_id` 隔离，绑定关系持久化到 DB，对话历史存内存
6. **不引入框架**：Core agent loop 保持纯手写，飞书层也是手写对接 `lark-oapi`

---

## 十一、构建顺序

### 阶段 1：飞书应用准备
1. 飞书开放平台创建应用，获取 App ID / App Secret
2. 开启机器人能力
3. 配置事件订阅 URL（先用 ngrok 等工具暴露本地 8000 端口）
4. 获取 Verification Token

### 阶段 2：飞书接入层
1. `feishu/auth.py` — tenant_access_token 管理 + Webhook 验签
2. `feishu/identity.py` — 绑定/查表逻辑
3. `feishu/adapter.py` — 消息格式转换 + 发送文本消息
4. `feishu/card.py` — 审批卡片构建 + 更新
5. `feishu/webhook.py` — 路由整合
6. `api.py` 挂载 `/feishu/webhook`

### 阶段 3：数据库变更
1. `db/models.py` — employees 加字段 + feishu_sessions 建表
2. `db/init_db.py` — 更新

### 阶段 4：联调验证
1. 启动服务，ngrok 暴露
2. 飞书开放平台配置回调地址
3. 验证：绑定 → 对话 → 请假 → 卡片审批 → 完整闭环

---

## 十二、核心约束

1. **不引入 LangChain 或 Agent 框架** — 纯手写
2. **工具函数不做合规检查** — 合规判断是 LLM 的职责
3. **所有工具函数返回字符串** — 给 LLM 阅读
4. **数据库操作用原生 SQL** — `text()` 执行
5. **现有 Agent 核心不动** — `core/agent.py`、工具函数零改动
6. **飞书层只做适配** — 不掺入业务逻辑
7. **API Key 全从环境变量读取**
8. **⚠️ Windows 编码** — `open()` 必须加 `encoding='utf-8'`，否则 GBK 解码报错。所有 Python 文件读写都用 UTF-8。
