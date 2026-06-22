# 对话总结 — HR Agent 系统设计

> 本文档用于新 Claude Code 会话快速恢复上下文。包含所有设计决策、当前状态、待做事项。

---

## 〇、新 Claude 的角色定位

**你是开发文档设计者，不是编码智能体。**

你的职责：
- 与我讨论需求，帮我理清思路
- 设计系统架构、工具规格、数据模型
- 撰写和更新 `DEVELOPMENT_GUIDE.md`、`FRONTEND_GUIDE.md`、`policies.md` 等指导文档
- 引导我做出设计决策，而不是替我做决定

你不能做的事：
- 直接写业务代码（tools/、core/、api.py 等）
- 执行数据库操作
- 安装依赖

你的工作流程：
1. 我提出想法 → 你追问、澄清、帮我拆解
2. 我们讨论出方案 → 你更新指导文档
3. 我把更新后的指导文档交给另一个 Claude Code（编码智能体）去实现

---

## 一、项目定位

**Agent-Native HR 系统**，不是传统 CRUD + AI。核心模式：
- 员工说人话 → Agent 查制度(RAG) → 判断合规 → 调工具执行 → 回复结果
- 50 人以下小团队，学习/内部使用

---

## 二、技术栈（全部已锁定）

| 项 | 选型 | 原因 |
|------|------|------|
| 对话模型 | `deepseek-v4-flash` | OpenAI 兼容，中文强，便宜 |
| 向量模型 | 智谱 `embedding-2` | OpenAI 兼容 |
| 向量存储 | `faiss-cpu` | 本地文件 |
| 数据库 | SQLite (`hr.db`) | 50 人够用 |
| ORM | SQLAlchemy `text()` 原生 SQL | 3 张表不需要 ORM 映射 |
| Agent 框架 | **零框架，纯手写 Python** | 40 行 Agent 循环，不引入 LangChain |
| 前端 | FastAPI + 原生 HTML/JS，SSE 流式 | 两页面：login + chat |
| 依赖 | 仅 6 个包 | openai, faiss-cpu, sqlalchemy, pymupdf, python-dotenv, numpy |
| 部署 | 一个 `uvicorn api:app` | FastAPI serve 静态文件 + API |

---

## 三、数据库设计（5 张表）🥏 新增 overtime_records

1. **employees** — 员工（id, name, department, position, manager_id, hire_date）
2. **leave_balances** — 假期余额（每人每种假期一行，含 total/used/year）
3. **leave_requests** — 请假申请（status: pending/approved/rejected/cancelled/revoked/completed_early）
4. **attendance_records** — 考勤打卡（date, check_in, check_out, status: normal/late/absent）
5. **overtime_records** 🆕 — 加班记录（date, hours, overtime_type: weekday/weekend/holiday, comp_hours, remaining_comp_hours, expires_at, status）

---

## 四、工具函数（20 个，🥏 新增 6 个）

### 请假（6 个）
| 工具 | 谁用 | 说明 |
|------|------|------|
| `create_leave_request` | 员工 | 提交请假，不做合规检查。🆕 支持 `auto_approve` 参数 |
| `approve_leave` | 管理者 | 审批通过，扣余额 |
| `reject_leave` | 管理者 | 审批拒绝，不扣余额 |
| `cancel_leave_request` | 员工 | 撤回 pending 状态申请 |
| `revoke_leave_request` | 管理者 | 撤销已批准但假期未开始的申请，退余额 |
| `list_pending_approvals` | 管理者 | 查看待审批列表 |

### 自动审批 🆕（1 个）
| 工具 | 说明 |
|------|------|
| `check_auto_approval` | 检查是否满足自动审批条件：年假 + ≤1天 + 余额够 + 提前≥1天 + 有上级 |

### 冲突检测 🆕（1 个）
| 工具 | 说明 |
|------|------|
| `check_department_conflict` | 检查同部门同期请假是否超阈值（max(1人, 30%)），只预警不阻止 |

### 查询（7 个，含原有）
| 工具 | 说明 |
|------|------|
| `search_policy` | RAG 检索 policies.md 制度 |
| `query_leave_balance` | 查假期余额 |
| `get_employee` | 查员工信息 |
| `get_my_leave_history` | 查请假记录 |
| `query_my_attendance` | 查考勤打卡记录 |
| `get_attendance_stats` | 月考勤统计（正常/迟到/缺勤） |
| `check_my_dashboard` | 仪表盘：🆕 加了调休过期提醒 |

### 加班 🆕（4 个）
| 工具 | 说明 |
|------|------|
| `submit_overtime` | 提交加班记录（事后记录制），自动计算调休时长 |
| `approve_overtime` | 审批加班，自动增加调休余额 |
| `reject_overtime` | 拒绝加班记录 |
| `query_overtime_balance` | 查调休余额含即将过期提醒 |

### 公司全景（1 个）
| 工具 | 说明 |
|------|------|
| `get_company_dashboard` | 🆕 加了部门人力冲突预警展示 |

---

## 五、Agent 核心设计

### Agent 循环（伪代码）
```
while tool_rounds < 5:
    调 DeepSeek → 判断 finish_reason
    如果是 tool_calls → 逐个执行 → 结果追加到 messages → 循环
    如果是 stop → 返回文本给用户
```

### System Prompt 关键规则
- **对话开始**：先调 `check_my_dashboard`，有异常先提醒
- **请假流程**：确认信息 → 查制度 → 查余额 → 判合规 → 提交
- **撤回/撤销**：pending 可自行撤回，approved+未开始可申请撤销
- **考勤查询**：展示迟到超 3 次时主动提醒全勤奖受影响
- **约束**：永远先查制度再回答，数字必须来自工具结果，不要编造

### 核心原则
- **工具不做合规判断** — 合规是 LLM 的职责，工具只做机械执行
- **所有工具返回字符串** — 给 LLM 阅读，不返回结构化对象
- **RAG 源是 policies.md** — 改制度只改这一个文件

---

## 六、前端设计

### 页面流程
```
login.html（选身份卡片）
    ↓ 点击
index.html?employee_id=xxx（聊天页，身份锁定，不提供切换）
```

### SSE 流式事件
| type | 含义 | 前端行为 |
|------|------|---------|
| `tool_call` | Agent 开始调工具 | 紫色脉冲状态行 "🔧 正在调用 xxx…" |
| `tool_result` | 工具执行完毕 | 状态行保持 |
| `token` | 流式文本 | 首 token 清除工具行，逐字追加到气泡 |
| `done` | 本轮结束 | 释放输入框 |

### 关键交互
- 进入聊天页自动发"你好"触发 dashboard 检查
- 服务端维护 session_id → {employee_id, history} 映射
- `/api/switch` 绑定身份并清空历史
- 退出回到登录页

---

## 七、种子数据测试意图

- 王小明（emp_003）年假已用完 → 测余额不足被拒
- 张总（emp_001）无上级 → 测自动通过
- 王小明迟到 6 次 → 测全勤奖预警
- 李经理缺勤 2 天 → 测管理视角异常

---

## 八、制度文档（policies.md）

包含章节：年假、事假、病假、婚假、丧假、产假/陪产假、加班调休、旷工、请假通用规则、请假撤回与销假、考勤制度、组织架构、系统自动提醒规则

---

## 九、项目的关键文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `policies.md` | ✅ 已更新 | 含自动审批规则、冲突预警、完善加班制度 |
| `DEVELOPMENT_GUIDE.md` | ✅ 已更新 | 新增 6 个工具规格 + overtime_records 表 + 测试场景 E-I |
| `FRONTEND_GUIDE.md` | ✅ 已完成 | SSE 流式 + 登录页 |
| 代码文件 | 🔧 部分实现 | 用户已自行修改了部分代码，三个新功能待实现 |

---

## 十、已讨论的扩展方向（已设计，待实现）

1. **自动审批** ✅ 已设计
   - 仅年假（未来加调休），同时满足 ≤1天 + 余额够 + 提前≥1天 + 有上级 → 自动通过
   - 新增 `check_auto_approval` 工具检查条件，`create_leave_request` 加 `auto_approve` 参数
   - 婚假/丧假/病假/事假/产假/陪产假不适用自动审批（情感因素或需审证明材料）
2. **冲突检测** ✅ 已设计
   - 阈值 `max(1人, ceil(部门人数×30%))`，只预警不阻止
   - 新增 `check_department_conflict` 工具，请假时 + 管理者仪表盘两处使用
3. **加班模块** ✅ 已设计
   - 事后记录制（不需提前申请），新增 `overtime_records` 表
   - 新增 `submit_overtime` / `approve_overtime` / `reject_overtime` / `query_overtime_balance`
   - 调休请假复用 `create_leave_request(leave_type='comp')`，最小单位 1 小时
   - `check_my_dashboard` 加调休过期提醒（14天内）
4. **主动推送提醒** — 需要定时任务 + 通知渠道，当前版本只做被动（对话时检查）

---

## 十一、给新会话的启动建议

```
你的角色：开发文档设计者，不是编码智能体。
请阅读 SESSION_SUMMARY.md 了解项目全貌和工作方式。

当前需要你做的是：和我讨论下一步的设计，
然后更新 DEVELOPMENT_GUIDE.md / FRONTEND_GUIDE.md / policies.md。
代码实现由另一个 Claude Code 来完成。
```
