"""飞书身份绑定 —— open_id ↔ employee_id 映射。"""
import re
import logging
from datetime import datetime
from sqlalchemy import text
from db.database import get_session
from feishu.card import send_binding_confirm_card

logger = logging.getLogger("feishu.identity")

# 工号格式: emp_ + 4位数字
_EMPLOYEE_ID_RE = re.compile(r"^emp_\d{4}$")

# ── 绑定状态机 ──
# 每个 chat_id 可能处于以下状态：
#   None          — 已绑定 或 空闲（未绑定也不在流程中）
#   "pending_eid" — 等待用户输入工号
# 确认步骤使用飞书卡片按钮，回调自带数据不依赖内存状态。
# 状态存内存（随服务重启清空），绑定关系持久化到 DB。
_pending_bindings: dict[str, dict] = {}


def get_employee_id(chat_id: str) -> str | None:
    """根据飞书 chat_id 获取已绑定的员工工号。

    检查顺序:
        1. feishu_sessions 表（已绑定的会话）
        2. 无记录 → 返回 None（需走绑定流程）

    Args:
        chat_id: 飞书会话 ID（单聊即 open_id）

    Returns:
        str | None: 绑定的员工工号，未绑定时返回 None
    """
    session = get_session()
    try:
        row = session.execute(
            text("SELECT employee_id FROM feishu_sessions WHERE chat_id = :chat_id"),
            {"chat_id": chat_id},
        ).fetchone()
        if row:
            return row.employee_id
        return None
    finally:
        session.close()


def start_binding(chat_id: str) -> str:
    """开始绑定流程。

    Args:
        chat_id: 飞书会话 ID

    Returns:
        str: 给用户的消息
    """
    _pending_bindings[chat_id] = {"state": "pending_eid", "employee_id": None, "employee_name": None}
    return (
        "你好！我是 HR 助手，请先绑定您的员工工号。\n"
        "格式：emp_ + 4位数字，例如 emp_0001"
    )


def handle_binding_message(chat_id: str, user_message: str) -> tuple[str, str | None]:
    """处理绑定流程中的用户消息。

    Args:
        chat_id:      飞书会话 ID
        user_message: 用户输入的文本

    Returns:
        (reply_text, employee_id | None):
            - 绑定未完成时 employee_id 为 None
            - 绑定完成时 employee_id 为有效工号，可开始 Agent 对话
    """
    state = _pending_bindings.get(chat_id)
    if not state:
        return ("绑定流程异常，请重新输入工号绑定。", None)

    current_state = state["state"]
    user_input = user_message.strip()

    if current_state == "pending_eid":
        return _handle_employee_id_input(chat_id, user_input)

    return ("绑定流程异常，请重新输入工号绑定。", None)


def _handle_employee_id_input(chat_id: str, user_input: str) -> tuple[str, str | None]:
    """验证工号输入：先校验格式，再查 DB → 发确认卡片。"""
    # 1. 格式校验（emp_ + 4位数字）
    if not _EMPLOYEE_ID_RE.match(user_input):
        return (
            f"工号格式为 emp_ + 4位数字，例如 emp_0001。\n"
            f"请重新输入：",
            None,
        )

    # 2. 查询员工是否存在
    session = get_session()
    try:
        row = session.execute(
            text("SELECT id, name, department, position FROM employees WHERE id = :id"),
            {"id": user_input},
        ).fetchone()

        if not row:
            return (
                f"未找到工号为 {user_input} 的员工，请检查后重新输入。",
                None,
            )

        # 3. 发确认卡片（按钮 value 携带全部数据，回调不依赖内存状态）
        send_binding_confirm_card(
            chat_id=chat_id,
            employee_id=row.id,
            employee_name=row.name,
            department=row.department,
            position=row.position,
        )
        # 卡片发出后清除内存状态，确认/取消由卡片回调处理
        _pending_bindings.pop(chat_id, None)

        return (
            f"已找到 {row.department} 的 {row.name}（{row.position}）。\n"
            f"请通过下方卡片确认您的身份。",
            None,
        )
    finally:
        session.close()


def confirm_binding(chat_id: str, employee_id: str, employee_name: str):
    """卡片回调：确认绑定。"""
    _save_binding(chat_id, employee_id)
    logger.info(f"绑定成功（卡片确认）: chat_id={chat_id} → {employee_id} ({employee_name})")


def cancel_binding(chat_id: str):
    """卡片回调：取消绑定。仅清理内存状态（如有残留）。"""
    _pending_bindings.pop(chat_id, None)
    logger.info(f"绑定取消（卡片）: chat_id={chat_id}")


def _save_binding(chat_id: str, employee_id: str):
    """保存绑定关系到数据库。"""
    session = get_session()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 更新 employees 表的 feishu_open_id
        session.execute(
            text("UPDATE employees SET feishu_open_id = :open_id WHERE id = :eid"),
            {"open_id": chat_id, "eid": employee_id},
        )

        # INSERT OR REPLACE 到 feishu_sessions
        session.execute(
            text(
                "INSERT OR REPLACE INTO feishu_sessions (chat_id, employee_id, created_at, updated_at) "
                "VALUES (:chat_id, :employee_id, :now, :now)"
            ),
            {"chat_id": chat_id, "employee_id": employee_id, "now": now},
        )

        session.commit()
    finally:
        session.close()


def is_binding_in_progress(chat_id: str) -> bool:
    """检查某个会话是否正在绑定流程中。"""
    return chat_id in _pending_bindings


def clear_binding_state(chat_id: str):
    """清除绑定状态（服务重启后内存清空，此方法供重置使用）。"""
    _pending_bindings.pop(chat_id, None)
