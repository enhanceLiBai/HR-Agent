// ── 会话管理 ──
const SESSION_KEY = 'hr_agent_session';
let sessionId = sessionStorage.getItem(SESSION_KEY);
let currentEmployeeId = null;  // 初始化时从服务端获取

// 无 session 跳回登录页
if (!sessionId) {
    window.location.href = '/static/login.html';
}

let isWaiting = false;

const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');

// ── 工具图标映射 ──
const TOOL_ICONS = {
    search_policy: '📖',
    query_leave_balance: '📊',
    create_leave_request: '📝',
    approve_leave: '✅',
    reject_leave: '❌',
    list_pending_approvals: '📋',
    get_employee: '👤',
    get_my_leave_history: '📜',
    cancel_leave_request: '↩️',
    revoke_leave_request: '↩️',
    query_my_attendance: '🕐',
    get_attendance_stats: '📈',
    check_my_dashboard: '📋',
    get_company_dashboard: '🏢',
};

// ── 初始化 ──
async function init() {
    // 通过 session 获取当前身份
    try {
        const statusResp = await fetch(`/api/status?session_id=${encodeURIComponent(sessionId)}`);
        if (!statusResp.ok) {
            // session 失效 → 清空并跳回登录页
            sessionStorage.removeItem(SESSION_KEY);
            window.location.href = '/static/login.html';
            return;
        }
        const statusData = await statusResp.json();
        currentEmployeeId = statusData.employee_id;

        document.getElementById('user-name').textContent = statusData.employee_info.split(' | ')[0] || statusData.employee_id;
        document.getElementById('user-dept').textContent = '';
        document.title = `HR Agent — ${statusData.employee_info.split(' | ')[0] || statusData.employee_id}`;
    } catch (err) {
        renderMessage('system', `❌ 网络错误：${err.message}`);
        return;
    }

    // 补充部门/职位信息
    try {
        const meResp = await fetch(`/api/me/${currentEmployeeId}`);
        if (meResp.ok) {
            const me = await meResp.json();
            document.getElementById('user-dept').textContent = `${me.department} · ${me.position}`;
        }
    } catch (_) { /* 非关键 */ }

    // 欢迎消息
    const name = document.getElementById('user-name').textContent;
    renderMessage('system', `👋 ${name}，欢迎使用 HR Agent！有什么可以帮你的？`);
}

// ── 消息渲染 ──
function renderMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;

    const text = document.createElement('div');
    text.className = 'message-text';
    text.textContent = content;
    div.appendChild(text);

    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

// ── 工具过程提示（紧凑状态行，位于 agent 输出上方）──
function renderToolStatus(toolName, displayName) {
    const div = document.createElement('div');
    div.className = 'tool-status';
    const icon = TOOL_ICONS[toolName] || '🔧';
    div.textContent = `${icon} 正在调用 ${displayName}…`;
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

// ── 流式 Agent 消息气泡 ──
let streamBubble = null;

function ensureStreamBubble() {
    if (!streamBubble) {
        streamBubble = document.createElement('div');
        streamBubble.className = 'message agent';

        const text = document.createElement('div');
        text.className = 'message-text';
        text.id = 'stream-text';
        streamBubble.appendChild(text);

        chatContainer.appendChild(streamBubble);
    }
    return streamBubble;
}

function appendStreamToken(token) {
    ensureStreamBubble();
    const el = document.getElementById('stream-text');
    el.textContent += token;
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function finalizeStreamBubble() {
    streamBubble = null;
    const el = document.getElementById('stream-text');
    if (el) el.removeAttribute('id');
}

// ── 发送消息（流式）──
async function sendMessage() {
    const message = userInput.value.trim();
    if (!message || isWaiting) return;

    userInput.value = '';
    renderMessage('user', message);
    isWaiting = true;
    sendBtn.disabled = true;

    // 流式消费 SSE
    await streamChat(message);
}

async function streamChat(message) {
    const toolElements = [];   // DOM 元素数组（按创建顺序）
    let toolsCleared = false;  // 首 token 到达时清掉所有工具提示
    streamBubble = null;

    // ── 清除所有工具进度提示 ──
    function clearToolProgress() {
        for (const el of toolElements) {
            if (el && el.parentNode) el.remove();
        }
        toolElements.length = 0;
    }

    // ── 将最后一个工具状态标记为”已完成” ──
    function markLastToolDone() {
        const lastEl = toolElements[toolElements.length - 1];
        if (lastEl && lastEl.parentNode) {
            lastEl.classList.add('done');
            // 将 “正在调用” 替换为 “已完成”
            const text = lastEl.textContent;
            const idx = text.indexOf('正在调用');
            if (idx !== -1) {
                lastEl.textContent = text.slice(0, idx) + '已完成' + text.slice(idx + 4);
            }
        }
    }

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, message }),
        });

        if (!response.ok) {
            const err = await response.json();
            renderMessage('system', `❌ ${err.detail || '请求失败'}`);
            return;
        }

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
                const jsonStr = line.slice(6);
                let event;
                try {
                    event = JSON.parse(jsonStr);
                } catch (_) {
                    continue;
                }

                switch (event.type) {
                    case 'tool_call':
                        toolsCleared = false;
                        // 新一轮工具调用前，清除上一轮的旧状态
                        clearToolProgress();
                        toolElements.push(renderToolStatus(event.tool, event.display));
                        break;

                    case 'tool_result':
                        // 工具执行完毕，更新状态行为“已完成”
                        markLastToolDone();
                        break;

                    case 'token':
                        if (!toolsCleared) {
                            clearToolProgress();
                            toolsCleared = true;
                        }
                        appendStreamToken(event.text);
                        break;

                    case 'done':
                        clearToolProgress();
                        finalizeStreamBubble();
                        break;

                    case 'error':
                        clearToolProgress();
                        renderMessage('system', `❌ ${event.message}`);
                        break;
                }
            }
        }
    } catch (err) {
        clearToolProgress();
        renderMessage('system', `❌ 网络错误：${err.message}`);
    } finally {
        clearToolProgress();  // 确保流异常终止时也清理工具状态
        isWaiting = false;
        sendBtn.disabled = false;
        userInput.focus();
    }
}

// ── 事件绑定 ──
sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ── 退出按钮 ──
document.getElementById('logout-btn').addEventListener('click', () => {
    sessionStorage.removeItem(SESSION_KEY);
    window.location.href = '/static/login.html';
});

// 启动
init();
