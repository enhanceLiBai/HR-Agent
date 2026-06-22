# HR Agent 前端开发指导文档

> 本文档是前端指令文档——Claude Code 按此规格构建 Web 界面。不改动已有后端代码。

---

## 一、前端架构

```
  浏览器打开 / → login.html（选择身份）
       │
       │ 选择员工 → 跳转
       ▼
  /static/index.html?employee_id=emp_003（聊天页，身份已锁定）
       │
       │ ① 进入时自动发"你好"触发 dashboard 检查
       │ ② 后续消息通过 SSE 流式返回
       ▼
  POST /api/chat/stream (SSE) → core/agent.py → chat_stream()
```

**两个页面，身份在进入聊天前已确定。聊天页内不提供身份切换。**

**通信方式：Server-Sent Events (SSE) 流式推送，前端实时展示工具调用过程 + 逐字输出回复。**

---

## 二、新增文件

```
hr-agent/
├── api.py                    ← 已有，需新增路由
├── static/
│   ├── login.html            ← 新增：身份选择页
│   ├── index.html            ← 新增：聊天页面
│   ├── style.css             ← 新增：样式（两页共用）
│   └── app.js                ← 新增：聊天逻辑
└── ...
```

---

## 三、后端 API

### 3.1 POST /api/chat/stream（主要接口）

前端通过 SSE 流式消费 Agent 回复。请求和 `/api/chat` 格式相同，但响应是 `text/event-stream`。

```
POST /api/chat/stream
Content-Type: application/json

请求体：
{
    "session_id": "<uuid>",
    "message": "你好"
}

响应（SSE 事件流）：
data: {"type":"tool_call","tool":"check_my_dashboard","display":"检查个人仪表盘"}

data: {"type":"tool_result","tool":"check_my_dashboard","display":"检查个人仪表盘","result_summary":"迟到6次…"}

data: {"type":"token","text":"您本月"}

data: {"type":"token","text":"已迟到"}

data: {"type":"done"}
```

SSE 事件类型：

| type | 含义 | 前端行为 |
|------|------|---------|
| `tool_call` | Agent 开始调用某个工具 | 显示紫色脉冲状态行 "🔧 正在调用 xxx…" |
| `tool_result` | 工具执行完毕 | 状态行保持不变，等待 Agent 开始回复 |
| `token` | 流式文本片段 | 首 token 到达时清除工具状态行，然后逐字追加到气泡 |
| `done` | 本轮回复结束 | 清理状态，释放输入框 |
| `error` | 异常 | 显示错误消息 |

### 3.2 POST /api/chat（非流式，CLI 用）

```
POST /api/chat
Content-Type: application/json

请求体：
{
    "session_id": "<uuid>",
    "message": "你好"
}

响应体（200）：
{
    "reply": "一切正常。本月迟到 6 次，已影响全勤奖。有什么可以帮你的？",
    "employee_id": "emp_003",
    "employee_info": "王小明 | 技术部 | 工程师 | 入职 2024-03-15 | 上级：李经理"
}
```

### 3.3 POST /api/switch

前端进入聊天页时调用，将会话绑定到选定员工。

```
POST /api/switch
Content-Type: application/json

请求体：
{
    "session_id": "<uuid>",
    "employee_id": "emp_003"
}

响应体（200）：
{
    "session_id": "<uuid>",
    "employee_id": "emp_003",
    "employee_info": "王小明 | 技术部 | 工程师 | 入职 2024-03-15 | 上级：李经理"
}
```

注意：切换身份会清空服务端对话历史。

### 3.4 GET /api/me/{employee_id}

```
GET /api/me/emp_003
→ {"id": "emp_003", "name": "王小明", "department": "技术部", "position": "工程师", "manager_name": "李经理", "is_manager": false}
```

### 3.5 GET /api/employees

```
GET /api/employees
→ [
    {"id": "emp_001", "name": "张总",   "department": "管理部", "position": "总经理"},
    {"id": "emp_002", "name": "李经理", "department": "技术部", "position": "部门总监"},
    {"id": "emp_003", "name": "王小明", "department": "技术部", "position": "工程师"}
]
```

登录页用这个接口获取可选身份列表。

### 3.6 会话机制

前端在 `localStorage` 中持久化一个 `session_id`（UUID）。服务端内存中维护 `{session_id → {employee_id, history}}` 映射。换身份时调 `/api/switch`，服务端清空 history 并更新 employee_id。

---

## 四、页面规格

### 4.1 登录页 (`login.html`)

```
┌──────────────────────────────────┐
│                                  │
│         🏢 HR Agent              │
│         智能人力资源助手           │
│                                  │
│  ┌────────────────────────────┐  │
│  │  👤 张总                    │  │
│  │     管理部 · 总经理          │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │  👤 李经理                  │  │
│  │     技术部 · 部门总监        │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │  👤 王小明                  │  │
│  │     技术部 · 工程师          │  │
│  └────────────────────────────┘  │
│                                  │
│         点击头像卡片进入          │
└──────────────────────────────────┘
```

核心逻辑：
- 页面加载时调 `GET /api/employees` 获取员工列表
- 每个员工一张卡片，点击后跳转 `index.html?employee_id=xxx`
- 无需密码，无需验证码，纯身份选择

### 4.2 聊天页 (`index.html`)

```
┌──────────────────────────────────────────────┐
│  HR Agent                   王小明 | 技术部    │
│                              [退出]            │
├──────────────────────────────────────────────┤
│                                               │
│  ┌─ 系统 ───────────────────────────────┐    │
│  │ 👋 王小明，欢迎回来。                 │    │
│  │ 正在检查您的最新状态…                 │    │
│  └─────────────────────────────────────┘    │
│                                               │
│  🔧 正在调用 检查个人仪表盘…   ← 紫色脉冲状态行  │
│  ┌─ Agent ───────────────────────────────┐   │
│  │ ⚠️ 本月已迟到 6 次，已影响全勤奖。     │   │
│  │ 有什么可以帮你的？                     │   │
│  └───────────────────────────────────────┘   │
│                                               │
│              ┌─ 我 ──────────────────────┐   │
│              │ 我想请明天一天年假          │   │
│              └───────────────────────────┘   │
│                                               │
│  🔧 正在调用 检索公司制度文档…                 │
│  🔧 正在调用 查询假期余额…                     │
│  ┌─ Agent ───────────────────────────────┐   │
│  │ 很抱歉，您本年度年假已用完…            │   │
│  └───────────────────────────────────────┘   │
│                                               │
├──────────────────────────────────────────────┤
│  [输入消息...                          ] [发送]│
└──────────────────────────────────────────────┘
```

核心逻辑：
- 从 URL 读取 `employee_id`，无参数则跳回登录页
- 调 `POST /api/switch` 绑定会话身份，再调 `GET /api/me/{id}` 展示身份信息在顶栏
- "退出"按钮跳回 `login.html`
- **进入后自动发"你好"触发 dashboard 检查**（无需用户手动输入第一句话）
- 消息发送使用 `POST /api/chat/stream`（SSE），实时流式渲染
- **顶栏不提供身份切换下拉框**

### 4.3 流式交互时序

```
用户发送消息
    │
    ▼
前端 fetch POST /api/chat/stream
    │
    ├─→ SSE: tool_call  → 渲染工具状态行 "🔧 正在调用 xxx…"（紫色脉冲）
    ├─→ SSE: tool_result → 状态行保持（等待回复开始）
    ├─→ SSE: token       → 首 token 到达时清除所有工具状态行，创建 Agent 气泡
    ├─→ SSE: token × N   → 逐字追加到气泡
    └─→ SSE: done        → 释放输入框
```

---

## 五、代码骨架

### 5.1 登录页 (`static/login.html`)

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HR Agent — 登录</title>
    <link rel="stylesheet" href="style.css">
</head>
<body class="login-page">
    <div class="login-container">
        <div class="login-header">
            <h1>🏢 HR Agent</h1>
            <p>智能人力资源助手</p>
        </div>
        <div id="employee-list" class="employee-cards">
            <!-- JS 动态填充 -->
        </div>
        <p class="login-hint">点击头像卡片进入</p>
    </div>
    <script>
        // 页面加载时获取员工列表并渲染卡片
        async function loadEmployees() {
            const resp = await fetch('/api/employees');
            const employees = await resp.json();
            const container = document.getElementById('employee-list');

            const icons = ['👤', '👤', '👤']; // 可替换为不同图标
            employees.forEach((emp, i) => {
                const card = document.createElement('div');
                card.className = 'employee-card';
                card.innerHTML = `
                    <div class="card-icon">${icons[i] || '👤'}</div>
                    <div class="card-name">${emp.name}</div>
                    <div class="card-info">${emp.department} · ${emp.position}</div>
                `;
                card.addEventListener('click', () => {
                    window.location.href = `/static/index.html?employee_id=${emp.id}`;
                });
                container.appendChild(card);
            });
        }
        loadEmployees();
    </script>
</body>
</html>
```

### 5.2 聊天页 (`static/index.html`)

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HR Agent — 智能助手</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div id="app">
        <header>
            <h1>HR Agent</h1>
            <div class="header-right">
                <span id="user-name"></span>
                <span id="user-dept"></span>
                <button id="logout-btn" onclick="window.location.href='/static/login.html'">退出</button>
            </div>
        </header>
        <main id="chat-container"></main>
        <footer>
            <textarea id="user-input" placeholder="输入消息，回车发送..." rows="1"></textarea>
            <button id="send-btn">发送</button>
        </footer>
    </div>
    <script src="app.js"></script>
</body>
</html>
```

### 5.3 聊天逻辑 (`static/app.js`)

核心设计：

| 模块 | 职责 |
|------|------|
| 会话管理 | `localStorage` 存 `session_id`，进入时调 `/api/switch` 绑定身份 |
| 自动问候 | `init()` 结束后自动调 `autoSendHello()` 发"你好"触发 dashboard |
| SSE 消费 | `streamChat()` 用 `fetch` + `ReadableStream` 读取 SSE，按事件类型分发 |
| 工具状态 | `tool_call` → 渲染紧凑状态行；首 `token` → 清除所有状态行 |
| 流式输出 | `token` → 逐字追加到当前 Agent 气泡 |

```javascript
// ── 会话管理 ──
const SESSION_KEY = 'hr_agent_session';
let sessionId = localStorage.getItem(SESSION_KEY);
if (!sessionId) { sessionId = crypto.randomUUID(); localStorage.setItem(SESSION_KEY, sessionId); }

// ── 初始化 ──
async function init() {
    // ① 绑定身份：POST /api/switch
    // ② 加载信息：GET /api/me/{employee_id}
    // ③ 自动发"你好"触发 dashboard 检查
    autoSendHello();
}

// ── SSE 流式消费（核心）──
async function streamChat(message) {
    const toolElements = {};       // tool_name → DOM 状态行
    let toolsCleared = false;

    const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const event = JSON.parse(line.slice(6));

            switch (event.type) {
                case 'tool_call':
                    // 显示状态行 "🔧 正在调用 xxx…"
                    toolElements[event.tool] = renderToolStatus(event.tool, event.display);
                    break;

                case 'token':
                    // 首 token → 清除所有工具状态行
                    if (!toolsCleared) { clearToolProgress(); toolsCleared = true; }
                    appendStreamToken(event.text);
                    break;

                case 'done':
                    clearToolProgress();
                    finalizeStreamBubble();
                    break;
            }
        }
    }
}

// ── 工具状态行 ──
function renderToolStatus(toolName, displayName) {
    const div = document.createElement('div');
    div.className = 'tool-status';
    div.textContent = `${TOOL_ICONS[toolName]} 正在调用 ${displayName}…`;
    chatContainer.appendChild(div);
    return div;
}

// ── 流式气泡 ──
let streamBubble = null;

function appendStreamToken(token) {
    if (!streamBubble) {
        streamBubble = document.createElement('div');
        streamBubble.className = 'message agent';
        const text = document.createElement('div');
        text.className = 'message-text';
        text.id = 'stream-text';
        streamBubble.appendChild(text);
        chatContainer.appendChild(streamBubble);
    }
    document.getElementById('stream-text').textContent += token;
    chatContainer.scrollTop = chatContainer.scrollHeight;
}
```

关键约束：
- **工具状态行不是消息气泡**，是紧凑的 `div.tool-status`，位于 Agent 气泡上方
- **首 token 到达时立刻清除所有工具状态行**，确保聊天记录干净
- **`streamBubble` 是复用的**，同一轮回复只创建一个气泡，token 追加到同一气泡

### 5.4 样式 (`static/style.css`)

```css
/* ===== 基础 ===== */
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; }

/* ===== 登录页 ===== */
.login-page { display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.login-container { text-align: center; max-width: 420px; width: 100%; padding: 40px 24px; }
.login-header h1 { font-size: 28px; margin-bottom: 8px; }
.login-header p { color: #64748b; margin-bottom: 32px; }
.employee-cards { display: flex; flex-direction: column; gap: 12px; }
.employee-card {
    display: flex; align-items: center; gap: 16px;
    padding: 16px 20px; background: white; border-radius: 12px;
    border: 2px solid #e2e8f0; cursor: pointer; transition: all 0.15s;
}
.employee-card:hover { border-color: #2563eb; box-shadow: 0 2px 12px rgba(37,99,235,0.15); }
.card-icon { font-size: 32px; }
.card-name { font-size: 16px; font-weight: 600; }
.card-info { font-size: 13px; color: #64748b; margin-left: auto; }
.login-hint { margin-top: 24px; font-size: 13px; color: #94a3b8; }

/* ===== 聊天页 ===== */
#app { max-width: 720px; margin: 0 auto; height: 100vh; display: flex; flex-direction: column; }
header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 20px; background: white; border-bottom: 1px solid #e2e8f0;
}
header h1 { font-size: 18px; }
.header-right { display: flex; align-items: center; gap: 12px; font-size: 14px; }
#user-dept { color: #64748b; font-size: 12px; }
#logout-btn {
    padding: 4px 12px; background: none; border: 1px solid #e2e8f0;
    border-radius: 6px; cursor: pointer; font-size: 12px; color: #64748b;
}
#logout-btn:hover { background: #f1f5f9; }

main {
    flex: 1; overflow-y: auto; padding: 16px 20px;
    display: flex; flex-direction: column; gap: 12px;
}
footer {
    display: flex; gap: 8px; padding: 12px 20px;
    background: white; border-top: 1px solid #e2e8f0;
}
footer textarea {
    flex: 1; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 8px;
    resize: none; font-size: 14px; font-family: inherit;
}
footer button {
    padding: 10px 20px; background: #2563eb; color: white;
    border: none; border-radius: 8px; cursor: pointer; font-size: 14px;
}
footer button:hover { background: #1d4ed8; }

/* ===== 消息气泡 ===== */
.message { max-width: 85%; }
.message.user { align-self: flex-end; }
.message.agent { align-self: flex-start; }
.message.system { align-self: center; max-width: 100%; }

.message-text {
    padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.6;
    white-space: pre-wrap;
}
.message.user .message-text { background: #2563eb; color: white; border-bottom-right-radius: 4px; }
.message.agent .message-text { background: #f1f5f9; color: #1e293b; border-bottom-left-radius: 4px; }
.message.system .message-text { background: #fef3c7; color: #92400e; text-align: center; font-size: 13px; }

/* ===== 工具状态行（agent 输出上方）===== */
.tool-status {
    align-self: flex-start;
    font-size: 12px;
    color: #7c3aed;
    padding: 0 0 2px 4px;
    animation: pulse 1.2s infinite;
}

/* ===== 加载动画 ===== */
@keyframes pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 1; }
}
```

---

## 六、页面流程

```
用户打开 http://localhost:8000
        │
        ▼
   GET / → 返回 /static/login.html
        │
        │ 点击 王小明 卡片
        ▼
   /static/index.html?employee_id=emp_003
        │
        │ 页面加载 → POST /api/switch 绑定身份
        │          → GET /api/me/emp_003 获取显示信息
        │          → 显示 "👋 王小明，欢迎回来。正在检查您的最新状态…"
        │
        │ 自动发 "你好"（无需用户手动输入）
        ▼
   POST /api/chat/stream (SSE)
        │
        ├─→ SSE: tool_call  → 显示 "📋 正在调用 检查个人仪表盘…"（紫色脉冲）
        ├─→ SSE: tool_result
        ├─→ SSE: token × N → 清除工具状态行 → 逐字输出 Agent 回复
        └─→ SSE: done
        │
        │ Agent 回复中会先告知 dashboard 提醒（如有异常），再回应用户
        ▼
   用户输入第二句话 → 同样走 SSE 流式
```

---

## 七、构建顺序

1. 后端：`api.py` 新增 `POST /api/chat`、`POST /api/chat/stream`、`POST /api/switch`、`GET /api/me/{id}`、`GET /api/employees`、`GET /api/status`
2. 后端：`core/agent.py` 实现 `chat_stream()` 流式生成器（SSE 事件产出）
3. 前端：创建 `static/login.html`、`static/index.html`、`static/style.css`、`static/app.js`
4. FastAPI 挂载 `/static` 静态文件，`/` 返回 `login.html`
5. 联调测试

---

## 八、测试场景

| 场景 | 操作 | 预期 |
|------|------|------|
| 登录选身份 | 打开页面 → 看到 3 张员工卡片 | 卡片内容正确 |
| 进入聊天 | 点击王小明 → 跳转聊天页 | 顶栏显示"王小明 · 技术部·工程师" |
| 自动问候 | 进入聊天后自动发"你好" | 无需手动输入，Agent 自动回复 |
| Dashboard 提醒 | 自动问候触发 | 显示工具状态行 "📋 正在调用 检查个人仪表盘…"，Agent 回复提示迟到 6 次 |
| 流式输出 | 任意消息 | Agent 回复逐字出现，工具状态行首字到达时消失 |
| 退出 | 点退出按钮 | 回到登录页 |
| URL 直接访问 | 访问 index.html 无参数 | 跳回登录页 |
