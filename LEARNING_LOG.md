# HR Agent 踩坑复盘与技术总结

> 这份文档记录了开发 HR Agent 过程中踩过的所有坑，每次问题和解决方案的技术原理。
> 目的是面试前可以讲清楚：我们遇到了什么问题，为什么会出现，怎么解决的。

---

## 目录

1. [Windows 编码问题](#1-windows-编码问题)
2. [新用户注册：假期余额显示为空](#2-新用户注册假期余额显示为空)
3. [登录后闪退：uvicorn 热重载清空会话](#3-登录后闪退uvicorn-热重载清空会话)
4. [Agent 认错人：get_or_create_session 的隐患](#4-agent-认错人get_or_create_session-的隐患)
5. [会话持久化：从纯内存到 SQLite 备份](#5-会话持久化从纯内存到-sqlite-备份)
6. [浏览器缓存：从手动版本号到 MD5 内容哈希](#6-浏览器缓存从手动版本号到-md5-内容哈希)
7. [多标签页冲突：localStorage → sessionStorage](#7-多标签页冲突localstorage--sessionstorage)
8. [ngrok → Cloudflare Tunnel：公网穿透方案对比](#8-ngrok--cloudflare-tunnel公网穿透方案对比)
9. [动态 HTML 注入：FastAPI 路由 vs StaticFiles](#9-动态-html-注入fastapi-路由-vs-staticfiles)
10. [项目架构决策复盘](#10-项目架构决策复盘)

---

## 1. Windows 编码问题

### 现象

Windows 上运行 Python，处理中文注释或字符串时报 `UnicodeDecodeError`。

### 根因

Windows 默认编码是 **GBK**（代码页 936），而 Python 3 默认用 UTF-8 读文件。当文件中包含中文（注释、字符串），`open()` 或 `ast.parse()` 会用 GBK 去解读 UTF-8 编码的内容，导致解码失败。

### 解决

所有 Python 文件操作显式指定编码：

```python
# ❌ 错误
with open("file.txt", "r") as f:
    content = f.read()

# ✅ 正确
with open("file.txt", "r", encoding="utf-8") as f:
    content = f.read()
```

在 PowerShell 中运行 Python 前设置环境变量：

```powershell
$env:PYTHONIOENCODING='utf-8'
```

### 面试怎么说

> "我在 Windows 上开发，遇到了跨平台编码问题。Python 在 Windows 下默认用 GBK 解码，我在项目中把所有文件操作都显式指定了 UTF-8 编码，并在 PowerShell 中设置了 `PYTHONIOENCODING` 环境变量，确保了中文数据的正确处理。"

---

## 2. 新用户注册：假期余额显示为空

### 现象

新员工注册后，查询假期余额返回 "未找到 xx 的 xx 假期记录"。

### 根因

注册逻辑只往 `employees` 表插入了员工信息，没有往 `leave_balances` 表插入默认假期余额。数据库查询自然找不到。

### 解决

在 `api_register()` 中，插入员工记录后，立即为 5 种标准假期类型初始化余额：

| 假期类型 | 总额 | 已用 | 说明 |
|---------|------|------|------|
| annual | 5 | 0 | 年假 |
| personal | 0 | 0 | 事假（不设额度） |
| sick | 0 | 0 | 病假（不设额度） |
| marriage | 3 | 0 | 婚假 |
| bereavement | 3 | 0 | 丧假 |

year 字段动态取 `date.today().year`，不硬编码。

### 面试怎么说

> "用户注册不仅是创建账号，还需要初始化关联数据。我把新用户的假期余额初始化和默认值的讨论（各假期类型应该给多少天）作为设计决策记录了下来。"

---

## 3. 登录后闪退：uvicorn 热重载清空会话

### 现象

登录成功后跳转到聊天界面，页面刚显示出来就被踢回登录页，"闪一下"。

### 触发链

```
1. 登录 → 后端 _create_session() → 会话存入内存 dict
2. 前端存 session_id 到 localStorage → 跳转 index.html
3. app.js init() → GET /api/status?session_id=xxx
4. 如果此时 uvicorn 检测到文件变更 → 自动重启 → 内存被清空
5. _lookup_session() 找不到 → 返回 401 → 前端清 localStorage → 跳回登录页
```

### 根因

两个因素叠加：

1. **`uvicorn.run(reload=True)`**：开发时监听文件变更，自动重启 worker 进程
2. **`sessions` 是纯内存存储**：`sessions: dict[str, dict] = {}`，进程重启就没了

### 解决

1. 关掉热重载：`reload=True` → 去掉，手动重启
2. 会话加 SQLite 持久化（见第 5 节）

### 面试怎么说

> "开发环境用了 uvicorn 的 auto-reload，每次改代码都会重启服务，而会话是存在内存里的。这导致了一个开发体验问题：登录成功后服务刚好 reload，前端验证会话时返回 401，用户被踢回登录页。我的解决方案是关掉了热重载，同时把会话持久化到了 SQLite。"

---

## 4. Agent 认错人：get_or_create_session 的隐患

### 现象

新用户注册后发消息，Agent 把它认成了 "王小明"（emp_003），展示了王小明的个人仪表盘。

### 触发链

```
1. 新用户注册 → _create_session() → sessions["abc"] = {employee_id: "emp_0005"}
2. app.js init() → /api/status → session 找到 → 正常
3. ── server reload，sessions 清空 ──
4. 用户发消息 → POST /api/chat/stream {session_id: "abc"}
5. get_or_create_session("abc") → 找不到 → 创建默认会话 → employee_id = "emp_003"！
6. System Prompt 注入 current_employee_id = "emp_003"
7. Agent 以王小明的身份执行所有工具调用
```

### 根因

两个端点对"会话不存在"的行为不一致：

| 端点 | 函数 | 找不到时的行为 |
|------|------|---------------|
| `/api/status` | `_lookup_session()` | 返回 None → 401 |
| `/api/chat/stream` | **`get_or_create_session()`** | **创建默认会话（emp_003）！** |

`get_or_create_session()` 的原始实现：

```python
def get_or_create_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "employee_id": "emp_003",  # ← 硬编码默认值！
            "history": [],
        }
    return sessions[session_id]
```

### 解决

1. **删除** `get_or_create_session()` 函数
2. **删除** `/api/switch` 端点（身份由登录决定，不可切换）
3. `/api/chat` 和 `/api/chat/stream` 改用 `_lookup_session()`，找不到直接返回 401

### 面试怎么说

> "我在设计会话管理时发现了一个安全问题：如果 chat 端点找不到会话就悄悄创建一个默认身份，那在 server 重启后，前端带着旧 session_id 发消息时，Agent 会以别人的身份执行操作。我的解决方案是统一行为：所有需要身份验证的端点都用 `_lookup_session`，找不到就 401，不让系统有'默认用户'这个概念。"

---

## 5. 会话持久化：从纯内存到 SQLite 备份

### 设计

内存作主存储（快），SQLite 作备份（重启恢复）。三层读写策略：

```
读：查内存 → 未命中 → 查 DB → 找到 → 恢复到内存
写：写内存 + 写 DB（UPSERT）
```

### 实现

**建表**（`db/models.py`）：

```sql
CREATE TABLE IF NOT EXISTS http_sessions (
    session_id   TEXT PRIMARY KEY,
    employee_id  TEXT NOT NULL,
    history      TEXT NOT NULL DEFAULT '[]',  -- JSON 序列化的对话历史
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**创建会话**：

```python
def _create_session(employee_id: str) -> str:
    sid = secrets.token_hex(16)
    sessions[sid] = {"employee_id": employee_id, "history": []}  # 写内存
    _persist_session_to_db(sid)  # 写 DB
    return sid
```

**查找会话**：

```python
def _lookup_session(session_id: str) -> dict | None:
    session = sessions.get(session_id)        # 1. 内存
    if session is not None:
        return session
    # 2. DB 恢复
    row = db.execute("SELECT ... FROM http_sessions WHERE session_id = ?")
    if row is None:
        return None
    sessions[session_id] = {"employee_id": row.eid, "history": json.loads(row.history)}
    return sessions[session_id]
```

**同步**：每次 chat 结束后，把最新的 `history` 更新到 DB（`ON CONFLICT ... DO UPDATE`）。DB 写操作包在 try/except 里，持久化失败不影响正常对话。

### 面试怎么说

> "我实现了一个两层缓存架构：内存 dict 做热数据访问，SQLite 做冷数据恢复。每次创建会话和对话完成后都同步写 DB。server 重启后，`_lookup_session` 会自动从 DB 恢复会话到内存，用户感受不到重启。"

---

## 6. 浏览器缓存：从手动版本号到 MD5 内容哈希

### 问题演进

| 阶段 | 做法 | 问题 |
|------|------|------|
| 最初 | 无版本号 | 浏览器永远用缓存 |
| 手动版 | `app.js?v=3` | 改代码容易忘更新版本号；部分浏览器（尤其是 HTTPS 下）对 query string 缓存不敏感 |
| MD5 哈希 | `app.js?v=a1b2c3d4` | 内容一变，版本号自动变，不需要人工维护 |

### 为什么 `?v=3` 有时不生效

浏览器的缓存策略：

- **强缓存**（`Cache-Control: max-age=...`）：完全跳过服务器，直接用本地缓存
- **协商缓存**（`ETag` / `Last-Modified`）：发请求问服务器"变了没？没变用缓存"
- 某些浏览器对静态文件的 query string 参数不敏感，仍然返回缓存版本 — 尤其 HTTPS 下

生产环境的做法是用 **文件名内嵌哈希**（如 `app.a1b2c3.js`），这样 URL 完全不同，浏览器不可能用缓存。

### 我们的方案

**不能改文件名**（因为没有构建工具），但让版本号变成文件内容的函数：

```python
def _compute_static_version() -> str:
    h = hashlib.md5()
    for fname in ["app.js", "style.css"]:
        with open(fname, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:8]

STATIC_VERSION = _compute_static_version()  # 启动时计算，如 "a1b2c3d4"
```

**HTML 用占位符**，服务端动态替换：

```html
<!-- 源码（静态文件） -->
<link href="/static/style.css?v=__VERSION__">
<script src="/static/app.js?v=__VERSION__">

<!-- 服务端返回的 HTML（动态替换后） -->
<link href="/static/style.css?v=a1b2c3d4">
<script src="/static/app.js?v=a1b2c3d4">
```

改了 `app.js` 或 `style.css` → 重启服务 → MD5 变了 → HTML 里的所有引用变成新版本号 → 浏览器认为是新 URL → 拉新文件。

### 面试怎么说

> "没有构建工具的情况下，我用 MD5 内容哈希实现了自动缓存爆破。启动时计算前端静态文件的哈希，注入到 HTML 的引用 URL 里。内容一变，版本号自动变，不需要人工维护。这模拟了 webpack 的 `[contenthash]` 机制。"

---

## 7. 多标签页冲突：localStorage → sessionStorage

### 现象

同一个浏览器开两个标签页，分别登录员工和管理员，身份会串。

### 根因

`localStorage` 是同源下 **所有标签页共享** 的：

```
标签页1: 登录员工   → localStorage.setItem("session_id", "abc")
标签页2: 登录管理员 → localStorage.setItem("session_id", "xyz")  ← 覆盖了！
标签页1: 发消息 → 读到 "xyz" → 变成了管理员身份
```

### 解决

`localStorage` → `sessionStorage`，一行代码不变：

| | localStorage | sessionStorage |
|---|---|---|
| 跨标签页共享 | ✅ 共享（打架） | ❌ 不共享（独立） |
| 刷新页面 | ✅ 保留 | ✅ 保留 |
| 关闭标签页 | ✅ 保留 | ✅ 自动清除 |

### 面试怎么说

> "我考虑了多标签页的使用场景。`localStorage` 在同源标签页之间共享，导致不同身份会互相覆盖。`sessionStorage` 按标签页隔离，正好满足'一个浏览器同时管理员工和管理员两个身份'的需求。"

---

## 8. ngrok → Cloudflare Tunnel：公网穿透方案对比

### 为什么换

| | ngrok 免费版 | Cloudflare Tunnel |
|---|---|---|
| 警告页 | ✅ 每个人都要点 | ❌ 没有 |
| 国内访问 | 一般（日本节点） | 更快 |
| Safari 兼容 | 偶有加载问题 | 正常 |
| 并发限制 | 有限流 | 无明确限制 |
| 自定义域名 | 付费才有 | 免费支持 |

### 技术原理

两者都是把公网请求通过加密隧道转发到本地端口：

```
用户浏览器 → 公网域名(ngrok/cloudflare) → 加密隧道 → localhost:8000
```

Cloudflare Tunnel 走的是 Cloudflare 全球 CDN 网络（他们的 Argo Tunnel），国内有香港节点，所以比 ngrok 日本节点快。

### 面试怎么说

> "我用了 Cloudflare Tunnel 做公网穿透，让朋友在手机上也能访问。对比过 ngrok 免费版（有警告页、Safari 加载慢），最终选了 Cloudflare Tunnel，体验更好。"

---

## 9. 动态 HTML 注入：FastAPI 路由 vs StaticFiles

### 问题

如果 HTML 走 StaticFiles，就是静态文件直出，没法注入动态版本号。

### 解决

在 FastAPI 里，显式路由的优先级 **高于** mount 的静态文件：

```python
# 这个显式路由会拦截 /static/index.html
@app.get("/static/index.html", response_class=HTMLResponse)
async def serve_index():
    return _serve_html("index.html")  # 读文件 + 替换 __VERSION__ + 加 no-cache 头

# 其他静态文件（JS/CSS/图片）走这个
app.mount("/static", NoCacheStaticFiles(directory=static_dir), name="static")
```

请求到来时，FastAPI 先匹配显式路由，命中了就用 `_serve_html()`，没命中才落到 StaticFiles。

### 面试怎么说

> "我利用 FastAPI 路由优先级高于 StaticFiles mount 的特性，对 HTML 页面做了动态注入。HTML 走 FastAPI 路由（注入 MD5 版本号 + no-cache 头），JS/CSS 走 StaticFiles（文件直出，URL 带版本号确保不被缓存）。"

---

## 10. 项目架构决策复盘

### 为什么不引入 LangChain

- **原因**：LangChain 太重，封装层次多，出问题不好排查。对于一个工具数量有限、流程固定的 HR Agent，直接手写 tool calling 循环更清晰、更可控。
- **代价**：要自己处理多轮对话、工具调用编排、SSE 流式输出。
- **收益**：对 Agent 内核的理解更深，面试有东西讲。

### 为什么不用前端框架

- **原因**：只有 3 个页面，组件复用需求低，引入 React/Vue 反而增加复杂度和启动时间。
- **代价**：代码组织靠全局变量和 DOM 操作，项目大了会难维护。
- **收益**：零构建环节，改完即刷新，开发反馈极快。

### 为什么用 SQLite

- **原因**：单机部署，并发低，不需要 MySQL/PostgreSQL 的多进程能力。
- **代价**：写并发是瓶颈（SQLite 只有一个写锁）。
- **收益**：零配置，数据库就是一个文件，备份就是 copy。

### 会话管理设计演进

```
阶段1: 纯内存 sessions dict         → 重启就丢
阶段2: 内存 + SQLite 双层           → 重启恢复
阶段3: sessionStorage 标签页隔离     → 多身份同时用
```

---

## 面试核心话术模板

> "我独立开发了一个 HR Agent 智能助手，核心是一个不依赖 LangChain 的 Agent 框架。我自己处理了 tool calling 的多轮编排、SSE 流式响应、system prompt 注入。前端用纯原生 JS，没有框架。
>
> "开发过程中踩了 Windows 编码、浏览器缓存、会话持久化、多标签页隔离这些坑，每个我都理解了原理并给出了解决方案。比如我实现了基于 MD5 内容哈希的自动缓存爆破——没有构建工具的情况下模拟了 webpack 的 contenthash 机制。
>
> "工程层面，我用 FastAPI 路由优先级拦截 HTML 请求做动态注入，会话管理用内存+SQLite 双层架构，前端用 sessionStorage 实现标签页隔离。项目通过 Cloudflare Tunnel 做了公网部署。"

---

## 技术知识点速查表

| 概念 | 一句话解释 |
|------|-----------|
| PBKDF2 | 密码哈希算法，加盐迭代防彩虹表 |
| SSE | Server-Sent Events，服务端单向推送流 |
| Tool Calling | LLM 返回 JSON 描述要调哪个函数，应用层执行后把结果发回 |
| System Prompt | 注入对话开头的指令，控制 Agent 行为 |
| `secrets.token_hex()` | 生成加密安全的随机十六进制字符串 |
| SQLite 写锁 | SQLite 同时只允许一个写操作，读可并发 |
| FASTAPI `_lookup` vs `get_or_create` | 严格校验（401） vs 宽松兜底（创建默认值） |
| `localStorage` vs `sessionStorage` | 跨标签页共享 vs 标签页隔离 |
| 内容哈希缓存爆破 | URL 含文件 MD5，内容变→URL 变→强制重拉 |
| Cloudflare Tunnel | 免费内网穿透，基于 Argo 隧道 |
