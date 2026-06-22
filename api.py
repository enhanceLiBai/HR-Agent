"""HR Agent Web API —— FastAPI 后端，把 chat() 暴露为 HTTP 接口。"""
import json
import os
import re
import sys
import secrets
import hashlib
import logging
from datetime import date, datetime

# 配置日志，方便排查飞书回调问题
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, field_validator
from core.agent import chat, chat_stream
from core.auth import hash_password, verify_password
from tools.employee import get_employee

# ── 数据库初始化（建表 + 迁移 + 种子数据）──
from db.database import init_db
init_db()

app = FastAPI(title="HR Agent", description="智能 HR 助手 Web 接口")

# 静态文件挂载（CSS、JS 等）—— 禁止缓存，确保前端更新即时生效
class NoCacheStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"cache-control"] = b"no-cache, no-store, must-revalidate"
                headers[b"pragma"] = b"no-cache"
                headers[b"expires"] = b"0"
                message["headers"] = list(headers.items())
            await send(message)
        await super().__call__(scope, receive, send_wrapper)

static_dir = os.path.join(os.path.dirname(__file__), "static")

def _compute_static_version() -> str:
    """取 app.js + style.css 内容的 MD5 前 8 位，作为缓存版本号。内容一变，版本号自动变。"""
    h = hashlib.md5()
    for fname in ["app.js", "style.css"]:
        path = os.path.join(static_dir, fname)
        try:
            with open(path, "rb") as f:
                h.update(f.read())
        except FileNotFoundError:
            pass
    return h.hexdigest()[:8]

STATIC_VERSION = _compute_static_version()

app.mount("/static", NoCacheStaticFiles(directory=static_dir), name="static")

# ── 会话管理（内存 + SQLite 持久化，重启不丢失）──
sessions: dict[str, dict] = {}


def _persist_session_to_db(session_id: str) -> None:
    """将会话的 history 同步到 SQLite。"""
    session = sessions.get(session_id)
    if session is None:
        return
    try:
        from db.database import get_session as get_db
        from sqlalchemy import text
        s = get_db()
        try:
            s.execute(
                text(
                    "INSERT INTO http_sessions (session_id, employee_id, history, updated_at) "
                    "VALUES (:sid, :eid, :hist, datetime('now')) "
                    "ON CONFLICT(session_id) DO UPDATE SET "
                    "history = :hist, updated_at = datetime('now')"
                ),
                {
                    "sid": session_id,
                    "eid": session["employee_id"],
                    "hist": json.dumps(session.get("history", []), ensure_ascii=False),
                }
            )
            s.commit()
        finally:
            s.close()
    except Exception as e:
        logging.warning(f"会话持久化失败（非致命）: {e}")


# ── 请求/响应模型 ──

class ChatRequest(BaseModel):
    session_id: str
    message: str



class ChatResponse(BaseModel):
    reply: str
    employee_id: str
    employee_info: str


class StatusResponse(BaseModel):
    session_id: str
    employee_id: str
    employee_info: str


class LoginRequest(BaseModel):
    employee_id: str
    password: str


class RegisterRequest(BaseModel):
    employee_id: str
    name: str
    department: str
    position: str
    password: str
    confirm_password: str

    @field_validator('employee_id')
    @classmethod
    def validate_employee_id(cls, v: str) -> str:
        if not re.match(r'^emp_\d{4}$', v):
            raise ValueError('工号格式错误，必须是 emp_ + 4 位数字，如 emp_0001')
        return v

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('两次输入的密码不一致')
        return v


class AuthResponse(BaseModel):
    session_id: str
    employee_id: str
    employee_info: str


# ── 静态 HTML（注入 MD5 版本号，彻底解决浏览器缓存）──

def _serve_html(filename: str) -> HTMLResponse:
    path = os.path.join(static_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("__VERSION__", STATIC_VERSION)
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/static/index.html", response_class=HTMLResponse)
async def serve_index():
    return _serve_html("index.html")

@app.get("/static/login.html", response_class=HTMLResponse)
async def serve_login():
    return _serve_html("login.html")

@app.get("/static/register.html", response_class=HTMLResponse)
async def serve_register():
    return _serve_html("register.html")


# ── API 路由 ──

def _lookup_session(session_id: str) -> dict | None:
    """查找已有会话。先查内存，找不到再查 SQLite，找到则恢复到内存。"""
    session = sessions.get(session_id)
    if session is not None:
        return session

    # ── 内存未命中 → 从 DB 恢复 ──
    try:
        from db.database import get_session as get_db
        from sqlalchemy import text
        s = get_db()
        try:
            row = s.execute(
                text("SELECT employee_id, history FROM http_sessions WHERE session_id = :sid"),
                {"sid": session_id}
            ).fetchone()
            if row is None:
                return None

            history = json.loads(row.history) if row.history else []
            session = {
                "employee_id": row.employee_id,
                "history": history,
            }
            sessions[session_id] = session  # 恢复到内存
            return session
        finally:
            s.close()
    except Exception as e:
        logging.warning(f"从 DB 恢复会话失败: {e}")
        return None


def _create_session(employee_id: str) -> str:
    """为新登录/注册创建会话，返回 session_id。同时持久化到 SQLite。"""
    sid = secrets.token_hex(16)
    sessions[sid] = {
        "employee_id": employee_id,
        "history": [],
    }
    _persist_session_to_db(sid)
    return sid


def _assign_manager(department: str, position: str) -> str | None:
    """注册时自动分配直属上级。返回 manager_id 或 None。"""
    from db.database import get_session as get_db
    from sqlalchemy import text
    s = get_db()
    try:
        # 1. 优先：同部门职位含"经理/总监/主管"的员工
        row = s.execute(
            text(
                "SELECT id FROM employees "
                "WHERE department = :dept "
                "AND (position LIKE '%经理%' OR position LIKE '%总监%' OR position LIKE '%主管%') "
                "ORDER BY hire_date LIMIT 1"
            ),
            {"dept": department}
        ).fetchone()
        if row:
            return row.id

        # 2. 其次：同部门中已是他人上级的员工
        row = s.execute(
            text(
                "SELECT DISTINCT e.id FROM employees e "
                "JOIN employees sub ON sub.manager_id = e.id "
                "WHERE e.department = :dept "
                "ORDER BY e.hire_date LIMIT 1"
            ),
            {"dept": department}
        ).fetchone()
        if row:
            return row.id

        # 3. 都没找到 → 无上级
        return None
    finally:
        s.close()


@app.post("/api/login", response_model=AuthResponse)
def api_login(req: LoginRequest):
    """用工号 + 密码登录。"""
    from db.database import get_session as get_db
    from sqlalchemy import text
    s = get_db()
    try:
        row = s.execute(
            text("SELECT id, name, department, position, password_hash FROM employees WHERE id = :id"),
            {"id": req.employee_id}
        ).fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="工号或密码错误")

        if not row.password_hash:
            raise HTTPException(status_code=401, detail="该账号尚未设置密码，请联系管理员")

        if not verify_password(req.password, row.password_hash):
            raise HTTPException(status_code=401, detail="工号或密码错误")

        # 创建会话
        sid = _create_session(req.employee_id)
        info = get_employee(req.employee_id)

        return AuthResponse(
            session_id=sid,
            employee_id=req.employee_id,
            employee_info=info,
        )
    finally:
        s.close()


@app.post("/api/register", response_model=AuthResponse)
def api_register(req: RegisterRequest):
    """注册新员工账号。"""
    from db.database import get_session as get_db
    from sqlalchemy import text

    # ── 字段非空校验 ──
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if not req.department.strip():
        raise HTTPException(status_code=400, detail="部门不能为空")
    if not req.position.strip():
        raise HTTPException(status_code=400, detail="职位不能为空")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要 6 个字符")

    s = get_db()
    try:
        # ── 查重 ──
        existing = s.execute(
            text("SELECT id FROM employees WHERE id = :id"),
            {"id": req.employee_id}
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail=f"工号 {req.employee_id} 已被注册")

        # ── 自动分配管理者 ──
        manager_id = _assign_manager(req.department.strip(), req.position.strip())

        # ── 插入员工 ──
        today = date.today().isoformat()
        pw_hash = hash_password(req.password)

        s.execute(
            text(
                "INSERT INTO employees (id, name, department, position, manager_id, hire_date, password_hash) "
                "VALUES (:id, :name, :dept, :pos, :mgr, :hire, :pw)"
            ),
            {
                "id": req.employee_id,
                "name": req.name.strip(),
                "dept": req.department.strip(),
                "pos": req.position.strip(),
                "mgr": manager_id,
                "hire": today,
                "pw": pw_hash,
            }
        )
        s.commit()

        # ── 初始化假期余额（5种标准类型，不包含 comp）──
        current_year = date.today().year
        default_balances = [
            ("annual",      5, 0),  # 年假：默认5天
            ("personal",    0, 0),  # 事假：不设额度
            ("sick",        0, 0),  # 病假：不设额度
            ("marriage",    3, 0),  # 婚假：3天
            ("bereavement", 3, 0),  # 丧假：3天
        ]
        for leave_type, total, used in default_balances:
            s.execute(
                text(
                    "INSERT INTO leave_balances (employee_id, leave_type, total, used, year) "
                    "VALUES (:eid, :ltype, :total, :used, :year)"
                ),
                {
                    "eid": req.employee_id,
                    "ltype": leave_type,
                    "total": total,
                    "used": used,
                    "year": current_year,
                }
            )
        s.commit()

        # ── 自动登录 ──
        sid = _create_session(req.employee_id)
        info = get_employee(req.employee_id)

        return AuthResponse(
            session_id=sid,
            employee_id=req.employee_id,
            employee_info=info,
        )
    finally:
        s.close()


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(req: ChatRequest):
    """发送消息，获取 Agent 回复。"""
    session = _lookup_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    employee_id = session["employee_id"]
    history = session["history"]

    try:
        reply = chat(req.message, employee_id, history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 错误: {str(e)}")
    finally:
        _persist_session_to_db(req.session_id)

    info = get_employee(employee_id)
    return ChatResponse(
        reply=reply,
        employee_id=employee_id,
        employee_info=info,
    )


@app.post("/api/chat/stream")
def api_chat_stream(req: ChatRequest):
    """发送消息，通过 SSE 流式返回 Agent 回复和工具调用过程。"""
    session = _lookup_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    employee_id = session["employee_id"]
    history = session["history"]

    def generate():
        try:
            for event in chat_stream(req.message, employee_id, history):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            _persist_session_to_db(req.session_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )



@app.get("/api/status", response_model=StatusResponse)
def api_status(session_id: str):
    """查询当前会话状态（仅在已登录时有效）。"""
    session = _lookup_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    employee_id = session["employee_id"]
    info = get_employee(employee_id)
    return StatusResponse(
        session_id=session_id,
        employee_id=employee_id,
        employee_info=info,
    )


@app.get("/api/employees")
def api_employees():
    """列出所有员工（供前端选择）。"""
    from db.database import get_session
    from sqlalchemy import text
    s = get_session()
    try:
        rows = s.execute(text("SELECT id, name, department, position FROM employees")).fetchall()
        return [
            {"id": r.id, "name": r.name, "department": r.department, "position": r.position}
            for r in rows
        ]
    finally:
        s.close()


@app.get("/api/me/{employee_id}")
def api_me(employee_id: str):
    """查询单个员工信息，返回 JSON。"""
    from db.database import get_session
    from sqlalchemy import text
    s = get_session()
    try:
        row = s.execute(
            text("SELECT id, name, department, position, manager_id FROM employees WHERE id = :id"),
            {"id": employee_id}
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"员工 {employee_id} 不存在")

        manager_name = None
        if row.manager_id:
            mgr = s.execute(
                text("SELECT name FROM employees WHERE id = :id"),
                {"id": row.manager_id}
            ).fetchone()
            if mgr:
                manager_name = mgr.name

        # 判断是否为管理者（有人以此人为上级）
        has_subordinates = s.execute(
            text("SELECT COUNT(*) FROM employees WHERE manager_id = :id"),
            {"id": employee_id}
        ).scalar()

        return {
            "id": row.id,
            "name": row.name,
            "department": row.department,
            "position": row.position,
            "manager_name": manager_name,
            "is_manager": has_subordinates > 0,
        }
    finally:
        s.close()


# ── 飞书 Webhook ──

@app.post("/feishu/webhook")
async def feishu_webhook(request: Request, background_tasks: BackgroundTasks):
    """飞书事件回调入口。

    3 秒超时应对：用 BackgroundTasks 异步处理 Agent 对话，
    收到请求后立刻返回 200。
    """
    # ── 原始请求日志（诊断用：确认请求是否到达）──
    _raw_log(f">>> 收到请求: {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}")

    body_str = await request.body()
    body = json.loads(body_str.decode("utf-8"))
    headers = dict(request.headers)
    _raw_log(f"    body type={body.get('type', 'N/A')}, event_type={body.get('header', {}).get('event_type', 'N/A')}")

    logger = logging.getLogger("api.feishu")

    # 1. URL 验证优先（飞书配置回调时触发，无需验签）
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info(f"URL 验证请求, challenge={challenge[:20]}...")
        _raw_log(f"    URL 验证: challenge={challenge[:30]}...")
        return JSONResponse(content={"challenge": challenge})

    # 2. 验签（事件处理前校验）
    from feishu.auth import verify_webhook_signature
    timestamp = headers.get("x-lark-request-timestamp", "")
    nonce = headers.get("x-lark-request-nonce", "")
    signature = headers.get("x-lark-signature", "")

    if not verify_webhook_signature(timestamp, nonce, body_str.decode("utf-8"), signature):
        logger.warning("验签失败，已忽略")
        _raw_log("    验签失败，返回 200")
        return JSONResponse(content={"code": 0})

    # 3. 记录事件类型，丢后台处理（带上原始请求体字符串用于内部验签）
    event_type = body.get("header", {}).get("event_type", "unknown")
    raw_body = body_str.decode("utf-8")  # 保留原始请求体字符串
    logger.info(f"收到事件: {event_type} → 提交后台处理")
    _raw_log(f"    验签通过，提交后台: {event_type}")

    background_tasks.add_task(_process_feishu_event, body, headers, raw_body)
    return JSONResponse(content={"code": 0})


def _process_feishu_event(body: dict, headers: dict, raw_body_str: str = ""):
    """后台函数：处理飞书事件（Agent 对话 / 卡片回调）。"""
    from feishu.webhook import process_webhook
    try:
        is_encrypted = "encrypt" in body
        _debug_log(f"开始处理: type={body.get('header', {}).get('event_type', 'N/A')}, encrypted={is_encrypted}")
        _debug_log(f"body keys: {list(body.keys())}, event keys: {list(body.get('event', {}).keys())}")
        process_webhook(body, headers, raw_body_str)
        _debug_log(f"处理完成")
    except Exception as e:
        _debug_log(f"异常: {e}")
        import traceback
        _debug_log(traceback.format_exc())


def _debug_log(msg: str):
    """把调试信息写到文件（后台线程 print 在 reload 模式下可能不显示）。"""
    with open(os.path.join(os.path.dirname(__file__), "_feishu_debug.log"), "a", encoding="utf-8") as f:
        from datetime import datetime
        f.write(f"{datetime.now().strftime('%H:%M:%S')} {msg}\n")


def _raw_log(msg: str):
    """写入原始请求日志（同步调用，诊断请求是否到达用）。"""
    try:
        log_path = os.path.join(os.path.dirname(__file__), "_feishu_raw.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ── 静态文件（前端）──

@app.get("/")
def serve_login():
    """根路径重定向到登录页。"""
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "static", "login.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def main():
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
