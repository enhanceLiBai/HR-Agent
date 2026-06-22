# CLAUDE.md — HR Agent 项目约定

## Windows 编码（最高优先级）

- **所有 Python 文件读写必须显式指定 `encoding='utf-8'`**，无论 `open()`、`ast.parse()`、还是 subprocess
- PowerShell 中运行 Python 脚本前，先设 `$env:PYTHONIOENCODING='utf-8'`
- 原因：Windows 默认 GBK，中文注释和字符串会报 `UnicodeDecodeError`

## 核心约束

- 不引入 LangChain 或任何 Agent 框架，纯手写
- 现有 `core/agent.py` 不动，现有 `tools/*.py` 不动
- 新代码放在 `feishu/` 目录下
- 数据库操作用 SQLAlchemy `text()` 执行原生 SQL
- API Key 全从 `.env` 读取

## 技术栈

- Python 3.11+，虚拟环境 `.venv`
- LLM: DeepSeek (`openai` SDK 兼容接口)
- 数据库: SQLite (`hr.db`)
- Web: FastAPI + uvicorn
- 飞书: `lark-oapi` SDK
- 向量: 智谱 embedding-2 + faiss-cpu

## 运行命令

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONIOENCODING='utf-8'
python api.py  # 启动在 127.0.0.1:8000
```
