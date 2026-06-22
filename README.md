# HR Agent — 智能人事助手

LLM Agent 系统，覆盖请假、加班、考勤、审批、制度检索、仪表盘等人事场景。支持 **Web 聊天界面**（SSE 流式）和 **飞书机器人**双入口。

## 技术栈

| 项 | 选型 |
|---|------|
| 对话模型 | DeepSeek（openai SDK 兼容接口） |
| 向量模型 | 智谱 embedding-2 |
| 向量存储 | FAISS（本地） |
| 数据库 | SQLite + SQLAlchemy text() 原生 SQL |
| Web 框架 | FastAPI + SSE 流式推送 |
| 飞书 SDK | lark-oapi（Webhook + 卡片消息） |
| Agent 框架 | 纯手写，零框架依赖 |

## 快速启动（Windows）

### 1. 环境准备

```powershell
# 创建虚拟环境
python -m venv .venv

# 激活
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

```powershell
cp .env.example .env
```

编辑 `.env`，填入以下必填项：

```ini
# 必填
DEEPSEEK_API_KEY=sk-your-key
ZHIPU_API_KEY=your-key

# 可选：飞书机器人（不启用飞书可不填）
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

### 3. 初始化数据库

```powershell
python -c "from db.models import create_tables; create_tables()"
python -c "from db.init_db import init_seed_data; init_seed_data()"
```

### 4. 启动 Web 服务

```powershell
$env:PYTHONIOENCODING='utf-8'
python api.py
```

浏览器打开 `http://127.0.0.1:8000`，注册/登录后即可使用。

### 5. （可选）启动飞书机器人

```powershell
$env:PYTHONIOENCODING='utf-8'
python feishu/webhook.py
```

需先在飞书开放平台配置应用，并将 Webhook 地址指向本服务。

## 项目结构

```
hr-agent/
├── .env.example                 # 环境变量模板
├── requirements.txt             # 依赖清单
├── policies.md                  # 公司制度（RAG 知识源）
├── api.py                       # FastAPI Web 入口
│
├── core/                        # 核心引擎
│   ├── agent.py                 # Agent 主循环（多轮 tool calling）
│   ├── context_manager.py       # 上下文窗口管理（滑动窗口 + 正则摘要）
│   ├── tool_registry.py         # 工具注册与执行分发
│   ├── tool_planner.py          # 工具按需路由（关键词 + 角色分组）
│   ├── system_prompt.py         # System Prompt 模板
│   └── auth.py                  # 登录认证
│
├── tools/                       # 业务工具（22 个）
│   ├── leave.py                 # 请假全流程
│   ├── overtime.py              # 加班全流程
│   ├── attendance.py            # 考勤查询
│   ├── employee.py              # 员工信息
│   ├── dashboard.py             # 仪表盘
│   └── policy.py                # RAG 制度检索
│
├── db/                          # 数据层
│   ├── database.py              # SQLAlchemy 连接
│   ├── models.py                # 建表
│   └── init_db.py               # 种子数据
│
├── rag/                         # RAG 检索
│   ├── loader.py                # PDF/MD 文档加载
│   ├── embedder.py              # 智谱 embedding-2 向量化
│   └── retriever.py             # FAISS 索引 + 检索
│
├── feishu/                      # 飞书集成
│   ├── webhook.py               # 消息处理 + 流式回复 + 卡片交互
│   ├── identity.py              # 飞书用户 ↔ 员工工号绑定
│   ├── card.py                  # 审批卡片构建
│   └── adapter.py               # 消息格式适配
│
└── static/                      # Web 前端（原生 HTML/CSS/JS）
    ├── index.html / app.js      # 聊天界面
    ├── login.html               # 登录页
    └── register.html            # 注册页
```

## 编码注意事项

- **所有 Python 文件操作必须 `encoding='utf-8'`**，Windows 默认 GBK 会导致中文报错
- PowerShell 运行 Python 前先 `$env:PYTHONIOENCODING='utf-8'`
