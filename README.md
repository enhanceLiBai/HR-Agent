# HR Agent - 智能助手

纯命令行交互的 HR 智能助手。员工通过自然语言与 Agent 对话完成请假，Agent 自动检索公司制度、判断合规性、调用工具执行业务操作。

## 技术栈

| 项 | 选型 |
|---|------|
| 对话模型 | DeepSeek v4 Flash |
| 向量模型 | 智谱 embedding-2 |
| 向量存储 | FAISS (本地) |
| 数据库 | SQLite |
| Web 框架 | FastAPI + 原生 HTML/JS |
| Agent 框架 | 纯手写，零框架 |

## 快速启动

### 方式一：Web 界面（推荐）

```bash
# 启动 Web 服务
python api.py
```

浏览器打开 `http://127.0.0.1:8000`，即可在聊天界面中使用。

### 方式二：命令行

```bash
python app.py
```

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 DeepSeek 和智谱 API Key：

```
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
ZHIPU_API_KEY=your-zhipu-api-key
```

### 3. 初始化数据库

```bash
python -c "from db.database import init_db; init_db()"
```

### 4. 构建 RAG 索引（首次运行自动构建）

首次运行时会自动从 `policies.md` 构建 FAISS 索引，也可以手动触发：

```bash
python -c "from rag.loader import load_policies; from rag.retriever import build_index; build_index(load_policies())"
```

### 5. 启动

```bash
python app.py
```

## 测试场景

### 场景 A：正常请假（员工视角）

```
当前身份: 王小明 | 技术部 | 工程师 | 上级：李经理
> 我想请一天年假，明天

Agent: 检索制度 → 查询余额 → 发现年假已用完
      "很抱歉，您本年度年假已用完（5.0天全部使用）。建议改为事假。"
```

### 场景 B：切换身份后正常请假

```
> switch emp_002
切换到: 李经理 | 技术部 | 部门总监 | 上级：张总
> 我要请年假，后天一天，家里装修

Agent: 检索制度 → 查询余额（剩余5天） → 提交申请
      "✅ 已提交。等待 张总 审批。"
```

### 场景 C：管理者审批

```
> 有要审批的吗

Agent: list_pending_approvals → 查看当前管理者的待审批列表
```

### 场景 D：总经理自动通过

```
> switch emp_001
切换到: 张总 | 管理部 | 总经理 | 上级：无
> 请一天年假

Agent: 无上级 → 自动通过
```

## 项目结构

```
hr-agent/
├── .env / .env.example         # 环境变量
├── requirements.txt            # 依赖清单
├── policies.md                 # 公司制度（RAG 知识源）
├── core/
│   ├── agent.py                # Agent 主循环
│   ├── tool_registry.py        # 工具注册与分发
│   └── system_prompt.py        # System Prompt
├── tools/
│   ├── policy.py               # search_policy —— RAG 检索制度
│   ├── leave.py                # 请假工具
│   └── employee.py             # 员工信息查询
├── rag/
│   ├── loader.py               # 加载 policies.md 并切片
│   ├── embedder.py             # 智谱 embedding 封装
│   └── retriever.py            # FAISS 索引 + 检索
├── db/
│   ├── database.py             # SQLAlchemy engine + session
│   ├── models.py               # 数据表模型
│   └── init_db.py              # 建表 + 种子数据
└── app.py                      # 命令行交互入口
```

## 修改制度

只需编辑 `policies.md`，重新构建 FAISS 索引即可，无需改动任何代码。

制度文档每条之间用 `---` 分隔。
