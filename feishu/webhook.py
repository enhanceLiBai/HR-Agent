"""飞书 Webhook 主路由 —— 消息/卡片事件处理 + Agent 编排。"""
import json
import os
import time
import logging
from datetime import datetime
from sqlalchemy import text

from feishu.auth import verify_webhook_signature, get_tenant_access_token, decrypt_event
from feishu.identity import (
    get_employee_id,
    start_binding,
    handle_binding_message,
    is_binding_in_progress,
)
from feishu.adapter import (
    extract_user_message,
    extract_chat_id,
    extract_message_id,
    extract_open_id,
    send_text_message,
    send_initial_message,
    update_message,
    get_message_type_description,
)
from feishu.card import (
    send_leave_approval_card,
    send_overtime_approval_card,
    update_card_approved,
    update_card_rejected,
    send_notification,
)
from core.agent import chat, chat_stream
from core.tool_registry import execute_tool
from db.database import get_session

logger = logging.getLogger("feishu.webhook")


# ── 调试日志 ──

def _debug_log(msg: str):
    """写入调试日志文件（后台线程 print 在 uvicorn reload 模式下可能不显示）。"""
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_feishu_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} [webhook] {msg}\n")
    except Exception:
        pass


# ── 对话历史（内存 + SQLite 持久化，按 chat_id 隔离）──
_conversation_histories: dict[str, list[dict]] = {}


def _get_history(chat_id: str) -> list[dict]:
    """获取会话历史（优先内存，首次从 DB 恢复）。"""
    if chat_id not in _conversation_histories:
        _conversation_histories[chat_id] = _load_history_from_db(chat_id)
    return _conversation_histories[chat_id]


def _load_history_from_db(chat_id: str) -> list[dict]:
    """从 feishu_sessions 表恢复对话历史。"""
    session = get_session()
    try:
        row = session.execute(
            text("SELECT history FROM feishu_sessions WHERE chat_id = :cid"),
            {"cid": chat_id},
        ).fetchone()
        if row and row.history:
            try:
                return json.loads(row.history)
            except json.JSONDecodeError:
                return []
        return []
    except Exception:
        return []
    finally:
        session.close()


def _save_history_to_db(chat_id: str):
    """将当前会话历史持久化到 feishu_sessions 表。"""
    history = _conversation_histories.get(chat_id, [])
    session = get_session()
    try:
        session.execute(
            text(
                "UPDATE feishu_sessions SET history = :hist, updated_at = datetime('now') "
                "WHERE chat_id = :cid"
            ),
            {"hist": json.dumps(history, ensure_ascii=False), "cid": chat_id},
        )
        session.commit()
    except Exception as e:
        logger.warning(f"会话历史持久化失败（非致命）: {e}")
    finally:
        session.close()


# ── Webhook 主入口 ──

def process_webhook(body: dict, headers: dict, raw_body_str: str | None = None) -> dict:
    """处理飞书 Webhook 请求。

    流程:
        1. 验签（URL 验证已由 api.py 短路处理；优先使用原始请求体）
        2. 事件分发 → 消息接收 / 卡片按钮点击
           - 消息: 身份绑定 → Agent 对话 → 回复
           - 卡片: 执行审批/拒绝 → 更新卡片 → 通知申请人

    Args:
        body:         请求体 JSON (dict)
        headers:      请求头 (dict-like)
        raw_body_str: 原始请求体字符串（用于验签），避免 json.dumps 重序列化差异

    Returns:
        dict: 响应体，通常 {"code": 0}
    """
    # ── 1. 验签 ──
    timestamp = str(headers.get("x-lark-request-timestamp", ""))
    nonce = str(headers.get("x-lark-request-nonce", ""))
    signature = str(headers.get("x-lark-signature", ""))
    # 优先用原始请求体字符串验签（避免 json.loads→json.dumps 造成字符串差异）
    sign_body = raw_body_str if raw_body_str is not None else json.dumps(body, ensure_ascii=False)

    if not verify_webhook_signature(timestamp, nonce, sign_body, signature):
        logger.warning("验签失败，返回 200 避免飞书重试（不处理请求）")
        _debug_log("❌ process_webhook 验签失败")
        return {"code": 0}

    # ── 2. 解密（飞书开启事件加密时 body 为 {"encrypt": "..."}) ──
    if "encrypt" in body:
        _debug_log(f"🔐 开始解密, encrypt_len={len(body.get('encrypt', ''))}")
        body = decrypt_event(body)
        if body is None:
            logger.error("事件解密失败，跳过处理")
            _debug_log("❌ 解密失败，跳过处理")
            return {"code": 0}
        _debug_log(f"✅ 解密成功, event_type={body.get('header', {}).get('event_type', 'unknown')}")

    # ── 3. 事件分发 ──
    event_type = body.get("header", {}).get("event_type", "")
    event = body.get("event", {})
    _debug_log(f"📨 事件分发: event_type={event_type}, event_keys={list(event.keys())}")

    if event_type == "im.message.receive_v1":
        _handle_message(event)
    elif event_type in ("im.message.action.trigger", "card.action.trigger", "card.action.trigger_v1"):
        _handle_card_action(event)
    else:
        logger.info(f"未处理的事件类型: {event_type}")
        _debug_log(f"⚠️ 未处理的事件类型: {event_type}")

    return {"code": 0}


# ── 流式回复 ──

def _stream_reply(chat_id: str, user_text: str, employee_id: str, history: list[dict]):
    """流式调用 Agent，通过消息更新模拟打字效果。

    流程：
      1. 先发 "⏳ 正在处理…" 占位消息
      2. 工具调用时 → 更新为 "🔧 正在查询…"
      3. token 流式到达 → 每 0.6 秒更新消息内容
      4. 完成 → 替换为最终完整文本
      5. 占位消息发送失败 → 降级为普通一次性发送
    """
    from core.agent import _tool_display_name

    # ── 1. 发送占位消息 ──
    message_id = send_initial_message(chat_id, "⏳ 正在处理…")
    if message_id is None:
        # 降级：占位消息发送失败，走传统一次性发送
        _debug_log("⚠️ 占位消息发送失败，降级为一次性发送")
        try:
            reply = chat(user_text, employee_id, history)
            send_text_message(chat_id, reply)
        except Exception:
            raise
        return

    _debug_log(f"📤 占位消息已发送: message_id={message_id[:20]}...")

    # ── 2. 流式调用 Agent ──
    content_parts: list[str] = []
    last_update = time.time()
    UPDATE_INTERVAL = 0.25   # 最快每 0.25 秒更新一次（飞书 PATCH 约 100-200ms）
    MIN_CHARS = 8            # 至少积累 8 个字再更新，避免频繁刷一个字
    first_token = True       # 首批 token 到达时立刻更新，不等间隔
    current_tool: str | None = None

    try:
        for event in chat_stream(user_text, employee_id, history):
            etype = event.get("type")

            if etype == "tool_call":
                current_tool = event.get("display", event.get("tool", ""))
                update_message(message_id, f"🔧 {current_tool}…")

            elif etype == "tool_result":
                current_tool = None
                # 不展示工具返回值细节，模型拿到就行

            elif etype == "token":
                content_parts.append(event["text"])
                now = time.time()
                partial = "".join(content_parts)
                should_update = False
                if first_token and len(partial) >= MIN_CHARS:
                    should_update = True
                    first_token = False
                elif now - last_update >= UPDATE_INTERVAL and len(partial) >= MIN_CHARS:
                    should_update = True
                if should_update:
                    update_message(message_id, partial + " ⏳")
                    last_update = now

            elif etype == "done":
                break

            elif etype == "error":
                update_message(message_id, f"❌ {event.get('message', '处理出错')}")
                return

    except Exception:
        # 流式过程出错 → 更新消息告知用户
        update_message(message_id, "❌ 抱歉，处理时遇到了问题，请稍后重试。")
        raise

    # ── 3. 最终更新卡片为完整回复 ──
    final_text = "".join(content_parts)
    if not final_text:
        final_text = "抱歉，未能生成回复，请重新描述您的问题。"

    _debug_log(f"📤 最终更新卡片: {len(final_text)} 字符")
    update_message(message_id, final_text)


# ── 消息处理 ──

def _handle_message(event: dict):
    """处理收到的单聊消息。"""
    message = event.get("message", {})
    chat_id = message.get("chat_id", "")
    if not chat_id:
        logger.warning("消息事件缺少 chat_id")
        _debug_log("❌ 消息事件缺少 chat_id")
        return

    # 提取用户文本
    user_text = extract_user_message({"event": event})
    _debug_log(f"chat_id={chat_id}, user_text={user_text!r}")
    _debug_log(f"  message_type={message.get('message_type') or message.get('msg_type')!r}, content={message.get('content', '')[:120]!r}")

    if user_text is None:
        # 非文本消息
        _debug_log("非文本消息，回复暂不支持")
        send_text_message(chat_id, get_message_type_description())
        return

    # ── 1. 身份绑定 ──
    employee_id = get_employee_id(chat_id)
    _debug_log(f"身份绑定状态: employee_id={employee_id}")

    if employee_id is None:
        # 未绑定，走绑定流程（不丢用户输入：先初始化状态，再立即处理当前消息）
        if not is_binding_in_progress(chat_id):
            start_binding(chat_id)
        reply, employee_id = handle_binding_message(chat_id, user_text)
        send_text_message(chat_id, reply)
        return

    # ── 2. 已绑定，走 Agent 对话（流式）──
    history = _get_history(chat_id)

    # 捕获 Agent 执行前的待审批请求 ID 集合（用于检测新创建的请求，避免重复发卡片）
    prior_pending_leaves = _get_pending_leave_ids()
    prior_pending_overtimes = _get_pending_overtime_ids()

    try:
        _stream_reply(chat_id, user_text, employee_id, history)
    except Exception as e:
        logger.error(f"Agent 处理异常: {e}")
        _debug_log(f"❌ Agent 异常: {e}")
        send_text_message(chat_id, f"抱歉，处理时遇到了问题：{str(e)}。请稍后重试。")

    # ── 3. 持久化会话历史 ──
    _save_history_to_db(chat_id)

    # ── 4. 飞书副作用：为新创建的 pending 请假/加班发送审批卡片 ──
    _send_cards_for_new_pending_leaves(prior_pending_leaves)
    _send_cards_for_new_pending_overtimes(prior_pending_overtimes)


# ── 卡片按钮处理 ──

def _handle_card_action(event: dict):
    """处理卡片按钮点击。兼容新旧版飞书卡片回调格式。"""
    action_info = event.get("action", {})
    raw_value = action_info.get("value", "{}")

    # v2 事件 value 可能已是 dict；v1 是 JSON 字符串；还可能被双重编码
    if isinstance(raw_value, dict):
        action_data = raw_value
    else:
        action_data = raw_value
        while isinstance(action_data, str):
            try:
                action_data = json.loads(action_data)
            except json.JSONDecodeError:
                break
        if not isinstance(action_data, dict):
            logger.error(f"无法解析 action value: {raw_value!r}")
            return

    action = action_data.get("action", "")

    # message_id 位置因事件版本不同：
    #   v1: event.message_id
    #   v2: event.context.open_message_id 或 event.context.message_id
    context = event.get("context", {})
    message_id = (
        context.get("open_message_id", "")
        or context.get("message_id", "")
        or event.get("message_id", "")
    )
    _debug_log(f"卡片回调: action={action}, message_id={message_id[:30] if message_id else 'EMPTY'}")

    # ── 绑定确认/取消（不需要已绑定身份）──
    if action == "confirm_binding":
        _handle_confirm_binding_card(action_data, message_id)
        return
    elif action == "cancel_binding":
        _handle_cancel_binding_card(action_data, message_id)
        return

    # ── 审批操作（需要已绑定身份）──
    request_id = action_data.get("request_id", "")
    approver_open_id = event.get("operator", {}).get("operator_id", {}).get("open_id", "")
    approver_id = get_employee_id(approver_open_id) or _find_employee_by_open_id(approver_open_id)

    if not approver_id:
        logger.warning(f"审批人未绑定: open_id={approver_open_id}")
        send_notification(approver_open_id, "请先在机器人中绑定员工身份后再审批。")
        return

    _debug_log(f"卡片动作: action={action}, request_id={request_id}, approver={approver_id}")

    if action == "approve_leave":
        _do_approve_leave(request_id, approver_id, message_id)
    elif action == "reject_leave":
        _do_reject_leave(request_id, approver_id, message_id)
    elif action == "approve_overtime":
        _do_approve_overtime(request_id, approver_id, message_id)
    elif action == "reject_overtime":
        _do_reject_overtime(request_id, approver_id, message_id)
    else:
        logger.warning(f"未知 action: {action}")


def _handle_confirm_binding_card(action_data: dict, message_id: str):
    """处理绑定确认卡片按钮（幂等：重复点击只更新卡片不重复绑定）。"""
    from feishu.identity import confirm_binding, get_employee_id
    from feishu.card import update_binding_card_confirmed

    employee_id = action_data.get("employee_id", "")
    employee_name = action_data.get("employee_name", "")
    chat_id = action_data.get("chat_id", "")

    already_bound = get_employee_id(chat_id)

    if not already_bound:
        confirm_binding(chat_id, employee_id, employee_name)
        from feishu.adapter import send_text_message
        send_text_message(chat_id, f"✅ 绑定成功！你好 {employee_name}，有什么可以帮你的？")

    # 更新卡片（无论是否已绑定都更新，防止卡片残留可点击状态）
    if message_id:
        update_binding_card_confirmed(message_id)


def _handle_cancel_binding_card(action_data: dict, message_id: str):
    """处理取消绑定卡片按钮。"""
    from feishu.identity import cancel_binding, get_employee_id
    from feishu.card import update_binding_card_cancelled

    chat_id = action_data.get("chat_id", "")
    already_bound = get_employee_id(chat_id)

    if not already_bound:
        cancel_binding(chat_id)
        from feishu.adapter import send_text_message
        send_text_message(chat_id, "已取消绑定。需要时请重新输入工号。")

    if message_id:
        update_binding_card_cancelled(message_id)


# ── 审批操作 ──

def _do_approve_leave(request_id: str, approver_id: str, message_id: str):
    """执行批准请假操作。"""
    result = execute_tool("approve_leave", {
        "request_id": request_id,
        "approver_id": approver_id,
        "comment": "",
    })

    if result.startswith("✅"):
        # 更新卡片为已批准（card.py 从缓存取原卡片 JSON）
        if message_id:
            update_card_approved(message_id)
        # 通知申请人
        _notify_applicant(request_id, result)
    else:
        # 审批失败（如已处理过），通知操作者
        approver_open_id = _find_open_id_by_employee(approver_id)
        if approver_open_id:
            send_notification(approver_open_id, result)


def _do_reject_leave(request_id: str, approver_id: str, message_id: str):
    """执行拒绝请假操作。"""
    result = execute_tool("reject_leave", {
        "request_id": request_id,
        "approver_id": approver_id,
        "reason": "审批人拒绝（通过卡片操作，如需补充具体原因请在此会话中说明）",
    })

    # 更新卡片为已拒绝
    if message_id:
        update_card_rejected(message_id, "审批人拒绝")
    # 通知申请人
    _notify_applicant(request_id, result)
    # 提示审批人可补充原因
    approver_open_id = _find_open_id_by_employee(approver_id)
    if approver_open_id:
        send_notification(
            approver_open_id,
            f"已拒绝 {request_id}。如需补充具体的拒绝原因，请在此输入，我会通知申请人。"
        )


def _do_approve_overtime(request_id: str, approver_id: str, message_id: str):
    """执行批准加班操作。"""
    result = execute_tool("approve_overtime", {
        "request_id": request_id,
        "approver_id": approver_id,
        "comment": "",
    })

    if result.startswith("✅"):
        if message_id:
            update_card_approved(message_id)
        _notify_applicant(request_id, result)
    else:
        approver_open_id = _find_open_id_by_employee(approver_id)
        if approver_open_id:
            send_notification(approver_open_id, result)


def _do_reject_overtime(request_id: str, approver_id: str, message_id: str):
    """执行拒绝加班操作。"""
    result = execute_tool("reject_overtime", {
        "request_id": request_id,
        "approver_id": approver_id,
        "reason": "审批人拒绝",
    })

    if message_id:
        update_card_rejected(message_id, "审批人拒绝")
    _notify_applicant(request_id, result)


# ── 飞书副作用：发送审批卡片 ──

def _send_cards_for_new_pending_leaves(prior_ids: set):
    """检测 Agent 执行后新创建的 pending 请假，给对应审批人发飞书卡片。"""
    session = get_session()
    try:
        rows = session.execute(
            text(
                "SELECT lr.id, lr.employee_id, lr.leave_type, lr.start_date, lr.end_date, "
                "lr.days, lr.reason, lr.approver_id, lr.created_at, e.name as applicant_name "
                "FROM leave_requests lr "
                "JOIN employees e ON lr.employee_id = e.id "
                "WHERE lr.status = 'pending' AND lr.approver_id IS NOT NULL "
                "ORDER BY lr.created_at DESC LIMIT 10"
            )
        ).fetchall()

        for row in rows:
            if row.id in prior_ids:
                continue  # 之前就存在的，不发卡片

            approver_open_id = _find_open_id_by_employee(row.approver_id)
            if not approver_open_id:
                logger.info(f"审批人 {row.approver_id} 未绑定飞书，跳过卡片发送")
                _debug_log(f"⚠️ 审批人 {row.approver_id} 未绑定飞书，无法发送审批卡片")
                # 通知申请人：主管未绑定，审批卡片未送达
                applicant_open_id = _find_open_id_by_employee(row.employee_id)
                if applicant_open_id:
                    send_notification(
                        applicant_open_id,
                        f"⚠️ 您的请假申请（{row.id}）已提交，但审批人尚未绑定飞书账号，"
                        f"审批卡片未能送达。请提醒主管在飞书中联系 HR 助手完成绑定。"
                    )
                continue

            _debug_log(f"📨 发送请假审批卡片: {row.id} → 审批人 {row.approver_id} (open_id={approver_open_id[:20]}...)")
            send_leave_approval_card(
                approver_open_id=approver_open_id,
                request_id=row.id,
                applicant_name=row.applicant_name,
                leave_type=row.leave_type,
                start_date=row.start_date,
                end_date=row.end_date,
                days=row.days,
                reason=row.reason or "",
            )
            logger.info(f"请假审批卡片已发送: {row.id} → {row.approver_id}")
    finally:
        session.close()


def _send_cards_for_new_pending_overtimes(prior_ids: set):
    """检测 Agent 执行后新创建的 pending 加班记录，给对应审批人发飞书卡片。"""
    session = get_session()
    try:
        rows = session.execute(
            text(
                "SELECT ot.id, ot.employee_id, ot.date, ot.hours, ot.overtime_type, "
                "ot.reason, ot.approver_id, ot.created_at, e.name as applicant_name "
                "FROM overtime_records ot "
                "JOIN employees e ON ot.employee_id = e.id "
                "WHERE ot.status = 'pending' AND ot.approver_id IS NOT NULL "
                "ORDER BY ot.created_at DESC LIMIT 10"
            )
        ).fetchall()

        for row in rows:
            if row.id in prior_ids:
                continue  # 之前就存在的，不发卡片（去重）

            approver_open_id = _find_open_id_by_employee(row.approver_id)
            if not approver_open_id:
                logger.info(f"审批人 {row.approver_id} 未绑定飞书，跳过卡片发送")
                _debug_log(f"⚠️ 审批人 {row.approver_id} 未绑定飞书，无法发送加班审批卡片")
                applicant_open_id = _find_open_id_by_employee(row.employee_id)
                if applicant_open_id:
                    send_notification(
                        applicant_open_id,
                        f"⚠️ 您的加班申请（{row.id}）已提交，但审批人尚未绑定飞书账号，"
                        f"审批卡片未能送达。请提醒主管在飞书中联系 HR 助手完成绑定。"
                    )
                continue

            _debug_log(f"📨 发送加班审批卡片: {row.id} → 审批人 {row.approver_id}")
            send_overtime_approval_card(
                approver_open_id=approver_open_id,
                request_id=row.id,
                applicant_name=row.applicant_name,
                overtime_date=row.date,
                hours=row.hours,
                overtime_type=row.overtime_type,
                reason=row.reason or "",
            )
            logger.info(f"加班审批卡片已发送: {row.id} → {row.approver_id}")
    finally:
        session.close()


# ── 辅助函数 ──

def _get_pending_leave_ids() -> set:
    """获取当前所有 pending 状态的请假申请 ID 集合。"""
    session = get_session()
    try:
        rows = session.execute(
            text("SELECT id FROM leave_requests WHERE status = 'pending'")
        ).fetchall()
        return {row.id for row in rows}
    finally:
        session.close()


def _get_pending_overtime_ids() -> set:
    """获取当前所有 pending 状态的加班记录 ID 集合。"""
    session = get_session()
    try:
        rows = session.execute(
            text("SELECT id FROM overtime_records WHERE status = 'pending'")
        ).fetchall()
        return {row.id for row in rows}
    finally:
        session.close()


def _notify_applicant(request_id: str, result_text: str):
    """通知申请人审批结果（通过飞书单聊消息）。"""
    session = get_session()
    try:
        # 查请假表
        row = session.execute(
            text("SELECT employee_id FROM leave_requests WHERE id = :id"),
            {"id": request_id},
        ).fetchone()

        if row:
            applicant_open_id = _find_open_id_by_employee(row.employee_id)
            if applicant_open_id:
                send_notification(applicant_open_id, result_text)
            return

        # 查加班表
        row = session.execute(
            text("SELECT employee_id FROM overtime_records WHERE id = :id"),
            {"id": request_id},
        ).fetchone()
        if row:
            applicant_open_id = _find_open_id_by_employee(row.employee_id)
            if applicant_open_id:
                send_notification(applicant_open_id, result_text)
    finally:
        session.close()


def _find_open_id_by_employee(employee_id: str) -> str | None:
    """根据 employee_id 查找对应的飞书 open_id。

    优先查 employees.feishu_open_id（绑定流程写入），
    回退查 feishu_sessions.chat_id（单聊场景下 chat_id 即 open_id）。
    """
    session = get_session()
    try:
        row = session.execute(
            text("SELECT feishu_open_id FROM employees WHERE id = :id"),
            {"id": employee_id},
        ).fetchone()
        if row and row.feishu_open_id:
            return row.feishu_open_id
        # 回退：feishu_sessions（单聊时 chat_id == open_id）
        row = session.execute(
            text("SELECT chat_id FROM feishu_sessions WHERE employee_id = :eid"),
            {"eid": employee_id},
        ).fetchone()
        return row.chat_id if row else None
    finally:
        session.close()


def _find_employee_by_open_id(open_id: str) -> str | None:
    """根据飞书 open_id 查找 employee_id。"""
    session = get_session()
    try:
        row = session.execute(
            text("SELECT id FROM employees WHERE feishu_open_id = :open_id"),
            {"open_id": open_id},
        ).fetchone()
        if row:
            return row.id
        row = session.execute(
            text("SELECT employee_id FROM feishu_sessions WHERE chat_id = :chat_id"),
            {"chat_id": open_id},
        ).fetchone()
        return row.employee_id if row else None
    finally:
        session.close()
