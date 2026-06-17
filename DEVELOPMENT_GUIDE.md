# HR Agent 开发指导文档

> 本文档是指令文档——Claude Code 按本文档的规格逐项构建系统。每项规格都已锁定，不可自行发挥。

---

## 一、项目概览

### 1.1 系统是什么

一个纯命令行交互的 HR 智能助手。员工通过自然语言与 Agent 对话完成请假，Agent 自动检索公司制度、判断合规性、调用工具执行业务操作。

### 1.2 技术栈（已锁定）

| 项 | 选型 | 说明 |
|---|------|------|
| 对话模型 | `deepseek-v4-flash` | OpenAI 兼容 API |
| 向量模型 | 智谱 `embedding-2` | OpenAI 兼容 API |
| 向量存储 | `faiss-cpu` | 本地文件，无需服务 |
| 数据库 | SQLite | 本地文件 `hr.db` |
| ORM | SQLAlchemy | 仅做连接管理，不搞复杂关系映射 |
| PDF 读取 | `pymupdf` | 制度文档如果是 PDF 格式 |
| 框架 | 零框架 | 纯手写 Python，不引入 LangChain |
| 语言 | Python 3.11+ | — |

### 1.3 依赖清单

```txt
openai>=1.0.0
faiss-cpu>=1.7.4
sqlalchemy>=2.0.0
pymupdf>=1.23.0
python-dotenv>=1.0.0
numpy>=1.24.0
```

只有 6 个依赖。`openai` 同时对接 DeepSeek 和智谱。

---

## 二、项目文件结构（已锁定）

```
hr-agent/
├── .env                      # API Key 等环境变量
├── .env.example              # 模板文件
├── requirements.txt          # 上面那份依赖清单
├── policies.md               # 公司制度文档（RAG 知识源）
├── core/
│   ├── __init__.py
│   ├── agent.py              # Agent 主循环
│   ├── tool_registry.py      # 工具注册与分发
│   └── system_prompt.py      # System Prompt 常量
├── tools/
│   ├── __init__.py
│   ├── policy.py             # search_policy —— RAG 检索制度
│   ├── leave.py              # 请假工具：查余额 / 提交申请 / 审批
│   └── employee.py           # 员工信息查询
├── rag/
│   ├── __init__.py
│   ├── loader.py             # 加载 policies.md 并切片
│   ├── embedder.py           # 智谱 embedding 封装
│   └── retriever.py          # FAISS 索引 + 检索
├── db/
│   ├── __init__.py
│   ├── database.py           # SQLAlchemy engine + session
│   ├── models.py             # 数据表模型
│   └── init_db.py            # 建表 + 种子数据
├── app.py                    # 命令行交互入口
└── README.md
```

---

## 三、数据库设计（已锁定）

### 3.1 表结构

```sql
-- 员工表
CREATE TABLE employees (
    id          TEXT PRIMARY KEY,        -- 工号，如 "emp_001"
    name        TEXT NOT NULL,           -- 真实姓名
    department  TEXT NOT NULL,           -- 部门名称
    position    TEXT NOT NULL,           -- 职位
    manager_id  TEXT,                    -- 直属上级工号，NULL 表示无上级（总经理）
    hire_date   TEXT NOT NULL,           -- 入职日期 "YYYY-MM-DD"
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 假期余额表
CREATE TABLE leave_balances (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id  TEXT NOT NULL,
    leave_type   TEXT NOT NULL,          -- annual / personal / sick / marriage / bereavement / maternity / paternity
    total        REAL NOT NULL,          -- 年度总额（天）
    used         REAL NOT NULL DEFAULT 0,-- 已使用（天）
    year         INTEGER NOT NULL,       -- 年份
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    UNIQUE(employee_id, leave_type, year)
);

-- 请假申请表
CREATE TABLE leave_requests (
    id               TEXT PRIMARY KEY,           -- "lv_" + 8位随机hex
    employee_id      TEXT NOT NULL,
    leave_type       TEXT NOT NULL,
    start_date       TEXT NOT NULL,              -- "YYYY-MM-DD"
    end_date         TEXT NOT NULL,              -- "YYYY-MM-DD"，单天则等于start_date
    days             REAL NOT NULL,              -- 天数，最小0.5
    reason           TEXT,                       -- 请假原因
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / rejected
    approver_id      TEXT,
    approver_comment TEXT,
    created_at       TEXT NOT NULL,
    resolved_at      TEXT,                       -- 审批时间
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (approver_id) REFERENCES employees(id)
);
```

### 3.2 种子数据

初始化脚本 (`db/init_db.py`) 需插入以下数据：

```python
# 3 个员工
employees = [
    {"id": "emp_001", "name": "张总",   "department": "管理部", "position": "总经理", "manager_id": None,      "hire_date": "2020-01-01"},
    {"id": "emp_002", "name": "李经理", "department": "技术部", "position": "部门总监", "manager_id": "emp_001", "hire_date": "2021-06-01"},
    {"id": "emp_003", "name": "王小明", "department": "技术部", "position": "工程师",   "manager_id": "emp_002", "hire_date": "2024-03-15"},
]

# 每人每种假期的年度余额（2026年）
leave_balances = [
    # emp_001: 张总
    {"employee_id": "emp_001", "leave_type": "annual",        "total": 5, "used": 2, "year": 2026},
    {"employee_id": "emp_001", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
    {"employee_id": "emp_001", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
    {"employee_id": "emp_001", "leave_type": "marriage",      "total": 3, "used": 0, "year": 2026},
    {"employee_id": "emp_001", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
    # emp_002: 李经理
    {"employee_id": "emp_002", "leave_type": "annual",        "total": 5, "used": 0, "year": 2026},
    {"employee_id": "emp_002", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
    {"employee_id": "emp_002", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
    {"employee_id": "emp_002", "leave_type": "marriage",      "total": 3, "used": 3, "year": 2026},
    {"employee_id": "emp_002", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
    # emp_003: 王小明
    {"employee_id": "emp_003", "leave_type": "annual",        "total": 5, "used": 5, "year": 2026},
    {"employee_id": "emp_003", "leave_type": "personal",      "total": 0, "used": 0, "year": 2026},
    {"employee_id": "emp_003", "leave_type": "sick",          "total": 0, "used": 0, "year": 2026},
    {"employee_id": "emp_003", "leave_type": "marriage",      "total": 3, "used": 0, "year": 2026},
    {"employee_id": "emp_003", "leave_type": "bereavement",   "total": 3, "used": 0, "year": 2026},
]
```

> 测试场景：王小明（emp_003）年假已用完，申请年假应被拒。张总（emp_001）无上级，申请自动通过。

---

## 四、工具函数规格（已锁定）

### 4.1 工具总览

| 工具名 | 用途 | 调用场景 |
|--------|------|---------|
| `search_policy` | RAG 检索公司制度 | 员工问制度问题 / 请假前合规检查 |
| `query_leave_balance` | 查某人的某假期余额 | 请假前确认是否还有额度 |
| `create_leave_request` | 提交请假申请 | 信息和合规检查都通过后 |
| `approve_leave` | 审批通过 | 管理者批准请假 |
| `reject_leave` | 审批拒绝 | 管理者拒绝请假 |
| `list_pending_approvals` | 查看待审批列表 | 管理者查看有哪些等着他批 |
| `get_employee` | 查询员工信息 | 需要知道员工姓名、部门、上级 |
| `get_my_leave_history` | 查自己的请假记录 | 员工回顾自己的请假历史 |

### 4.2 每个工具的精确规格

#### search_policy

```python
def search_policy(query: str) -> str:
    """
    在 policies.md 中检索与查询相关的制度规定。

    实现：
        1. 调用智谱 embedding-2 将 query 转为向量
        2. 用 FAISS 在预建索引中检索 top-3 最相似的文档片段
        3. 将 3 个片段用 "\n---\n" 拼接返回
        4. 如果 FAISS 索引未初始化，先调用 build_index() 构建

    参数:  query - 自然语言查询，如 "年假最多能请几天" 或 "病假需要什么证明"
    返回:  相关制度文本片段，如未找到则返回 "未找到相关制度规定。"
    """
```

#### query_leave_balance

```python
def query_leave_balance(employee_id: str, leave_type: str) -> str:
    """
    查询指定员工的某种假期余额。

    实现：
        1. 在 leave_balances 表中查询 (employee_id, leave_type, year=2026) 的记录
        2. 计算 remaining = total - used
        3. 返回人类可读的结果描述

    参数:  employee_id - 员工工号
           leave_type   - 假期类型，必须是以下之一:
                          annual(年假) / personal(事假) / sick(病假) /
                          marriage(婚假) / bereavement(丧假) /
                          maternity(产假) / paternity(陪产假)

    返回:  "年假：总额5.0天，已用2.0天，剩余3.0天"
           如果无记录: "未找到 emp_001 的 annual 假期记录"
           如果余额为0: "年假：总额5.0天，已用5.0天，剩余0.0天（已用完）"
    """
```

#### create_leave_request

```python
def create_leave_request(
    employee_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str
) -> str:
    """
    创建一条请假申请，状态为 pending。

    实现：
        1. 生成唯一 ID："lv_" + 8位hex（用 secrets.token_hex(4)）
        2. 计算天数 days = (end_date - start_date).days + 1
           - 如果 leave_type 是 annual，支持 0.5 天：start_date == end_date 且 reason 中提到"半天" → days=0.5
        3. 调用 get_employee(employee_id) 获取 manager_id 作为默认审批人
        4. 插入 leave_requests 表，status='pending', created_at=当前时间
        5. 返回确认信息

    参数:  employee_id - 申请人工号
           leave_type   - 假期类型
           start_date   - 开始日期 "YYYY-MM-DD"
           end_date     - 结束日期 "YYYY-MM-DD"（单天则等于 start_date）
           reason       - 请假原因

    返回:  "✅ 请假申请已提交（编号 lv_a1b2c3d4）
           类型：年假  日期：2026-06-18 至 2026-06-18  天数：1.0天
           状态：等待 李经理 审批"

    注意:  此函数不做合规检查，合规检查由 Agent 在调用前完成。
    """
```

#### approve_leave

```python
def approve_leave(request_id: str, approver_id: str, comment: str = "") -> str:
    """
    审批通过一条请假申请。

    实现：
        1. 在 leave_requests 表中查找 request_id
        2. 校验 status == 'pending'，否则返回错误
        3. 校验 approver_id 是否为该申请的审批人（或其上级），否则返回权限不足
        4. 更新 status='approved', approver_id=当前审批人, approver_comment=comment, resolved_at=当前时间
        5. 如果是带薪假期（annual/marriage/bereavement/maternity/paternity），
           在 leave_balances 表中扣减对应额度：used += days
        6. 事假(personal)和病假(sick)不扣年假额度

    参数:  request_id   - 申请编号
           approver_id  - 审批人工号
           comment      - 审批意见（可选）

    返回:  "✅ 已批准 lv_a1b2c3d4（年假 1.0天），已扣除年假余额。"
           或 "❌ 该申请已被处理，无法重复审批。"
           或 "❌ 权限不足：该申请需上级审批。"
    """
```

#### reject_leave

```python
def reject_leave(request_id: str, approver_id: str, reason: str) -> str:
    """
    拒绝一条请假申请。

    实现：
        1. 查找 request_id，校验 status == 'pending'
        2. 校验权限
        3. 更新 status='rejected', approver_comment=reason, resolved_at=当前时间
        4. 不扣减假期余额

    参数:  request_id   - 申请编号
           approver_id  - 审批人工号
           reason       - 拒绝原因

    返回:  "已拒绝 lv_a1b2c3d4（年假 1.0天），原因：{reason}"
    """
```

#### list_pending_approvals

```python
def list_pending_approvals(manager_id: str) -> str:
    """
    列出等待某管理者审批的所有请假申请。

    实现：
        1. 查询 leave_requests 表 status='pending' 且 approver_id=manager_id 的记录
        2. JOIN employees 获取申请人姓名
        3. 格式化为列表

    参数:  manager_id - 管理者的工号

    返回:  "您有 2 条待审批请假：
           [lv_a1b2c3d4] 王小明 - 年假 1.0天 (2026-06-18) 理由：家里有事
           [lv_e5f6g7h8] 王小明 - 病假 2.0天 (2026-06-20至2026-06-21) 理由：发烧"
           如无待审批: "您目前没有待审批的请假申请。"
    """
```

#### get_employee

```python
def get_employee(employee_id: str) -> str:
    """
    查询单个员工信息。

    实现：
        1. 查询 employees 表
        2. 如果有 manager_id，查出 manager 的 name
        3. 格式返回

    参数:  employee_id - 工号

    返回:  "王小明 | 技术部 | 工程师 | 入职 2024-03-15 | 上级：李经理"
           如不存在: "未找到工号为 emp_999 的员工。"
    """
```

#### get_my_leave_history

```python
def get_my_leave_history(employee_id: str, limit: int = 10) -> str:
    """
    查询员工的请假历史记录。

    实现：
        1. 查询 leave_requests 表中 employee_id 匹配的记录
        2. 按 created_at 降序排列，取前 limit 条
        3. 格式返回

    参数:  employee_id - 工号
           limit        - 返回条数，默认 10

    返回:  "您的最近请假记录：
           1. [lv_a1b2c3d4] 年假 1.0天 (2026-06-18) - 已批准
           2. [lv_e5f6g7h8] 病假 2.0天 (2026-05-10至2026-05-11) - 已批准
           3. [lv_i9j0k1l2] 年假 0.5天 (2026-04-03) - 已拒绝"
    """
```

### 4.3 工具 JSON Schema（给 DeepSeek 的 tools 参数）

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "检索公司假期和考勤制度文档。当员工询问任何关于假期规定、请假条件、考勤规则的问题时，必须先调用此工具查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询语句，如'年假可以请几天'、'病假需要什么证明'、'婚假怎么休'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_leave_balance",
            "description": "查询员工的某种假期余额。在提交请假申请前必须调用，确认员工有足够余额。",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "员工工号，如 emp_001"},
                    "leave_type": {
                        "type": "string",
                        "enum": ["annual", "personal", "sick", "marriage", "bereavement", "maternity", "paternity"],
                        "description": "假期类型"
                    }
                },
                "required": ["employee_id", "leave_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_leave_request",
            "description": "创建请假申请。只有在制度合规、余额充足的前提下才调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "申请人工号"},
                    "leave_type": {"type": "string", "description": "假期类型"},
                    "start_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD，单天与 start_date 相同"},
                    "reason": {"type": "string", "description": "请假原因"}
                },
                "required": ["employee_id", "leave_type", "start_date", "end_date", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "approve_leave",
            "description": "审批通过一条请假申请。仅管理者使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "申请编号"},
                    "approver_id": {"type": "string", "description": "审批人工号"},
                    "comment": {"type": "string", "description": "审批意见（可选）"}
                },
                "required": ["request_id", "approver_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reject_leave",
            "description": "拒绝一条请假申请。仅管理者使用。需填写拒绝原因。",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "申请编号"},
                    "approver_id": {"type": "string", "description": "审批人工号"},
                    "reason": {"type": "string", "description": "拒绝原因"}
                },
                "required": ["request_id", "approver_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_approvals",
            "description": "列出等待某管理者审批的所有请假申请。",
            "parameters": {
                "type": "object",
                "properties": {
                    "manager_id": {"type": "string", "description": "管理者的工号"}
                },
                "required": ["manager_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee",
            "description": "查询员工信息，包括部门、职位、入职日期、上级。",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "员工工号"}
                },
                "required": ["employee_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_leave_history",
            "description": "查询员工的请假历史记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "员工工号"},
                    "limit": {"type": "integer", "description": "返回条数，默认10"}
                },
                "required": ["employee_id"]
            }
        }
    }
]
```

---

## 五、RAG 模块规格（已锁定）

### 5.1 文档加载

- 源文件：`policies.md`
- 分块策略：按 `---` 分隔符切分。每个 `---` 之间的内容为一个 chunk
- 每个 chunk 保留标题行（`## xxx`）作为上下文
- 预期产生约 12-15 个 chunk

### 5.2 Embedding

- 模型：智谱 `embedding-2`
- API 地址：`https://open.bigmodel.cn/api/paas/v4/`
- SDK：`openai.OpenAI(base_url="...")`
- 维度：`embedding-2` 输出 1024 维
- 批次处理：单次调用可传多个 chunk，但为简单起见，逐条调用也可

### 5.3 向量索引

- 使用 FAISS `IndexFlatIP`（内积相似度，等价于余弦相似度当向量已归一化）
- 索引文件保存为 `rag/faiss_index.bin`，首次启动时若已存在则加载，否则从 policies.md 重新构建
- 检索时返回 top-3 结果，每个结果包含原始文本

### 5.4 检索接口

```python
# rag/retriever.py
def build_index(chunks: list[str]) -> None:
    """对 chunks 编码并构建 FAISS 索引，保存到文件"""
    ...

def search(query: str, top_k: int = 3) -> list[str]:
    """检索与 query 最相关的 top_k 个 chunk"""
    ...

# 如果索引文件存在就加载，不存在就构建
```

---

## 六、Agent 主循环规格（已锁定）

### 6.1 核心流程

```
用户输入消息
    │
    ▼
追加到 messages 列表
    │
    ▼
┌────────────────────────────────┐
│ 调用 DeepSeek chat.completions │
│ model: deepseek-v4-flash       │
│ messages: system + history     │
│ tools: TOOLS                   │
└────────────┬───────────────────┘
             │
             ▼
     response.choices[0].message
             │
    ┌────────┴────────┐
    │                  │
 tool_calls 存在    tool_calls 为空
    │                  │
    ▼                  ▼
逐个执行工具      返回 msg.content
    │              给用户（结束）
    ▼
结果追加到 messages
（role: "tool"）
    │
    ▼
回到顶部继续循环
（最多 5 轮工具调用）
```

### 6.2 代码骨架

```python
# core/agent.py
import json
import secrets
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

# 根据 .env 配置
client = OpenAI(
    api_key="sk-xxx",
    base_url="https://api.deepseek.com/v1",
)

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
    history.append({"role": "user", "content": user_message})

    # 将 employee_id 注入 system prompt，让模型知道当前用户
    system_content = SYSTEM_PROMPT.format(
        current_employee_id=employee_id,
        current_date="2026-06-17"  # TODO: 用 datetime.now()
    )

    messages = [{"role": "system", "content": system_content}] + history

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
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
```

### 6.3 工具注册

```python
# core/tool_registry.py
def execute_tool(name: str, args: dict) -> str:
    """根据工具名分发到对应的执行函数"""
    from tools.policy import search_policy
    from tools.leave import (
        query_leave_balance,
        create_leave_request,
        approve_leave,
        reject_leave,
        list_pending_approvals,
    )
    from tools.employee import get_employee, get_my_leave_history

    registry = {
        "search_policy":          lambda: search_policy(args["query"]),
        "query_leave_balance":    lambda: query_leave_balance(args["employee_id"], args["leave_type"]),
        "create_leave_request":   lambda: create_leave_request(args["employee_id"], args["leave_type"], args["start_date"], args["end_date"], args["reason"]),
        "approve_leave":          lambda: approve_leave(args["request_id"], args["approver_id"], args.get("comment", "")),
        "reject_leave":           lambda: reject_leave(args["request_id"], args["approver_id"], args["reason"]),
        "list_pending_approvals": lambda: list_pending_approvals(args["manager_id"]),
        "get_employee":           lambda: get_employee(args["employee_id"]),
        "get_my_leave_history":   lambda: get_my_leave_history(args["employee_id"], args.get("limit", 10)),
    }

    func = registry.get(name)
    if not func:
        return f"❌ 未知工具: {name}"
    try:
        return func()
    except Exception as e:
        return f"❌ 工具执行错误 ({name}): {str(e)}"
```

---

## 七、System Prompt（已锁定）

```python
# core/system_prompt.py
SYSTEM_PROMPT = """你是一个智能 HR 助手，帮助员工处理请假事务。

## 当前上下文
- 当前员工工号：{current_employee_id}
- 当前日期：{current_date}
- 当前年份：2026

## 你的职责
1. 回答员工关于公司假期制度、考勤规则的咨询
2. 帮助员工提交请假申请
3. 协助管理者审批或拒绝请假

## 工作流程

### 当员工表达请假意图时，严格按以下步骤操作：

第1步 ─ 确认信息：搞清楚请假类型、日期、原因
  - 员工没说类型 → 引导选择：年假、事假、病假、婚假、丧假、调休、产假/陪产假
  - 员工没说日期 → 追问具体日期
  - 员工没说原因 → 追问请假原因

第2步 ─ 查制度：调用 search_policy 检索该类型的制度规定
  - 必须查！不能凭记忆回答制度问题

第3步 ─ 查资格：调用 query_leave_balance 查看员工余额
  - 带薪假期（年假、婚假、丧假、产假、陪产假）需检查额度

第4步 ─ 综合判断：
  合规且余额够 → 告知员工各项条件满足，确认后提交
  不合规 → 清楚告知哪里不合规，给出替代建议
  需补充材料（婚假要结婚证、病假要医院证明） → 提醒员工准备

第5步 ─ 执行：调用 create_leave_request 提交申请

### 当管理者要审批/拒绝请假时：

1. 先调用 list_pending_approvals 列出待审批
2. 管理者选择要处理的申请
3. 调用 approve_leave 或 reject_leave 执行

### 当员工询问制度或查询信息时：

1. 制度类问题 → 先调用 search_policy 检索
2. 假期余额查询 → 调用 query_leave_balance
3. 个人请假记录 → 调用 get_my_leave_history
4. 员工信息查询 → 调用 get_employee

## 约束规则
- 永远先查制度再回答，不允许凭记忆编造公司规定
- 涉及天数、余额等数字，必须来自工具查询结果，不能自己编
- 如果工具调用失败或返回异常，如实告知用户，不要掩盖
- 工具返回什么就基于什么回答，不要添油加醋
- 不要跳过合规检查直接提交申请
- 如果员工年假余额为 0，要明确告知并建议其他假期类型
- 语气友善、简洁、专业，像真实的 HR 同事

## 不在你职责范围内的事
- 薪资计算和查询（尽管制度提到了薪资）
- 修改已有的请假记录
- 处理加班申请（当前版本不支持）
- 处理离职、入职等其他人事流程
"""
```

---

## 八、命令行交互入口规格

### 8.1 设计

```python
# app.py
def main():
    print("=" * 50)
    print("  HR Agent - 智能助手")
    print("  输入 'quit' 退出，输入 'switch <工号>' 切换身份")
    print("=" * 50)

    # 默认以王小明身份登录
    current_user = "emp_003"
    history = []

    print(f"\n当前身份: {get_employee(current_user)}")
    print("\n有什么可以帮你的？")

    while True:
        user_input = input("\n> ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("再见！")
            break
        if user_input.lower().startswith("switch "):
            new_id = user_input.split()[1]
            print(f"切换到: {get_employee(new_id)}")
            current_user = new_id
            history = []  # 切换身份清空历史
            continue

        response = chat(user_input, current_user, history)
        print(f"\n{response}")
```

### 8.2 测试对话场景（必须能跑通）

**场景 A：正常请假（员工视角）**
```
当前身份: 王小明 | 技术部 | 工程师 | 上级：李经理
> 我想请一天年假，明天

Agent: search_policy("年假规定") → ... → query_balance → 你没年假了
       "很抱歉，您本年度年假已用完（5.0天全部使用）。建议改为事假。"
```

> 注意：种子数据中王小明年假已用完，这个测试验证 Agent 能正确拒绝。

**场景 B：切换身份后正常请假**
```
> switch emp_002
切换到: 李经理 | 技术部 | 部门总监 | 上级：张总
> 我要请年假，后天一天，家里装修

Agent: search_policy → query_balance（剩余5天） → create_leave_request
       "✅ 已提交。编号 lv_xxx，等待 张总 审批。"
```

**场景 C：管理者审批**
```
> 有要审批的吗

Agent: list_pending_approvals("emp_002") → 当前为李经理，不是待审批列表的所有者
       "您没有待审批的请假。"
```

**场景 D：总经理自动通过**
```
> switch emp_001
切换到: 张总 | 管理部 | 总经理 | 上级：无
> 请一天年假

Agent: 张总无上级，创建申请后状态如何？按制度"无上级则自动通过"，
       approve_leave 中的审批人校验逻辑需处理此情况。
```

---

## 九、构建顺序（严格按此顺序执行）

### 阶段 1：基础设施
1. 创建项目目录结构
2. 编写 `requirements.txt`
3. 编写 `.env.example`，让用户填 API Key
4. 编写 `db/database.py` —— SQLAlchemy 连接
5. 编写 `db/models.py` —— 3 张表的模型
6. 编写 `db/init_db.py` —— 建表 + 插入种子数据
7. **验证**：运行 `init_db.py`，确认 `hr.db` 生成且数据正确

### 阶段 2：RAG 模块
1. 编写 `rag/embedder.py` —— 封装智谱 embedding
2. 编写 `rag/loader.py` —— 加载 policies.md 并按 `---` 切分
3. 编写 `rag/retriever.py` —— FAISS 索引构建 + 检索
4. **验证**：调用 `search("年假能请几天")` 确认返回相关制度文本

### 阶段 3：工具函数
1. 编写 `tools/employee.py` —— get_employee, get_my_leave_history
2. 编写 `tools/leave.py` —— query_leave_balance, create_leave_request, approve_leave, reject_leave, list_pending_approvals
3. 编写 `tools/policy.py` —— search_policy（调用 RAG 模块）
4. **验证**：在 Python 中直接调用每个函数，确认数据库操作正确

### 阶段 4：Agent 主循环
1. 编写 `core/system_prompt.py`
2. 编写 `core/tool_registry.py`
3. 编写 `core/agent.py` —— chat() 函数
4. **验证**：写一个简单测试脚本，模拟对话

### 阶段 5：命令行入口
1. 编写 `app.py`
2. **验证**：运行上面 4 个测试场景，逐条对话确认

### 阶段 6：收尾
1. 编写 `README.md`（项目说明 + 启动步骤）
2. 修正测试中发现的问题

---

## 十、环境变量

```bash
# .env.example
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash

ZHIPU_API_KEY=your-zhipu-api-key
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ZHIPU_EMBEDDING_MODEL=embedding-2
```

---

## 十一、关键约束（Claude Code 必须遵守）

1. **不要引入 LangChain 或任何 Agent 框架** —— 纯手写
2. **工具函数不要做合规检查** —— 合规判断是 Agent（LLM）的职责，工具只做机械执行
3. **所有工具函数返回字符串** —— 给 LLM 阅读的，不是给程序解析的
4. **数据库操作用原生 SQL** —— 通过 SQLAlchemy 的 `text()` 执行，不用 ORM 关系映射
5. **日志打印用 `print`** —— 开发阶段不要引入 logging 模块，保持简单
6. **API Key 从环境变量读取** —— 禁止硬编码
7. **每个阶段验证通过再进入下一阶段** —— 不要一口气全写完
