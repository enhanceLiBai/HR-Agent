"""审批卡片构建与发送 —— 给审批人发卡片消息，按钮一键审批。"""
import json
import logging
import requests
from feishu.auth import get_tenant_access_token

logger = logging.getLogger("feishu.card")

FEISHU_BASE = "https://open.feishu.cn/open-apis"

# ── 已发送卡片缓存 ──
# key=message_id, value=card JSON 深拷贝。
# 飞书按钮回调不携带原卡片内容，需要自己缓存才能更新卡片状态。
_sent_cards: dict[str, dict] = {}


def _cache_card(message_id: str, card: dict):
    """缓存已发送的卡片 JSON，供后续审批后更新卡片状态。"""
    _sent_cards[message_id] = json.loads(json.dumps(card))


def _pop_cached_card(message_id: str) -> dict | None:
    """取出并移除缓存的卡片。取不到说明服务重启过，返回 None。"""
    return _sent_cards.pop(message_id, None)


# ── 假期/加班类型中文名 ──
_TYPE_NAMES = {
    "annual": "年假", "personal": "事假", "sick": "病假",
    "marriage": "婚假", "bereavement": "丧假",
    "maternity": "产假", "paternity": "陪产假", "comp": "调休假",
    "weekday": "工作日加班", "weekend": "休息日加班", "holiday": "法定节假日加班",
}


def send_leave_approval_card(
    *,
    approver_open_id: str,
    request_id: str,
    applicant_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float,
    reason: str,
) -> bool:
    """给审批人发送请假审批卡片。

    Args:
        approver_open_id: 审批人的飞书 open_id
        request_id:       请假申请编号 (lv_xxx)
        applicant_name:   申请人姓名
        leave_type:       假期类型
        start_date:       开始日期
        end_date:         结束日期
        days:             请假天数
        reason:           请假原因

    Returns:
        bool: 发送成功返回 True
    """
    type_cn = _TYPE_NAMES.get(leave_type, leave_type)
    date_range = start_date if start_date == end_date else f"{start_date} 至 {end_date}"

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "📋 待审批：请假申请"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**申请人：**{applicant_name}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**类型：**{type_cn}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**日期：**{date_range}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**天数：**{days} 天"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**原因：**{reason or '无'}"},
            },
            {
                "tag": "hr",
            },
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"申请编号：{request_id}"}
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 批准"},
                        "type": "primary",
                        "value": json.dumps({
                            "action": "approve_leave",
                            "request_id": request_id,
                        }),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                        "type": "danger",
                        "value": json.dumps({
                            "action": "reject_leave",
                            "request_id": request_id,
                        }),
                    },
                ],
            },
        ],
    }

    return _send_card(approver_open_id, card)


def send_overtime_approval_card(
    *,
    approver_open_id: str,
    request_id: str,
    applicant_name: str,
    overtime_date: str,
    hours: float,
    overtime_type: str,
    reason: str,
) -> bool:
    """给审批人发送加班审批卡片。

    Args:
        approver_open_id: 审批人的飞书 open_id
        request_id:       加班记录编号 (ot_xxx)
        applicant_name:   申请人姓名
        overtime_date:    加班日期
        hours:            加班小时数
        overtime_type:    加班类型
        reason:           加班原因

    Returns:
        bool: 发送成功返回 True
    """
    type_cn = _TYPE_NAMES.get(overtime_type, overtime_type)

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "🕐 待审批：加班记录"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**申请人：**{applicant_name}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**类型：**{type_cn}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**日期：**{overtime_date}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**小时：**{hours} 小时"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**原因：**{reason or '无'}"},
            },
            {
                "tag": "hr",
            },
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"记录编号：{request_id}"}
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 批准"},
                        "type": "primary",
                        "value": json.dumps({
                            "action": "approve_overtime",
                            "request_id": request_id,
                        }),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                        "type": "danger",
                        "value": json.dumps({
                            "action": "reject_overtime",
                            "request_id": request_id,
                        }),
                    },
                ],
            },
        ],
    }

    return _send_card(approver_open_id, card)


def update_card_approved(message_id: str) -> bool:
    """更新卡片为「已批准」状态（从缓存取出原卡片 JSON 修改后推送更新）。

    Args:
        message_id: 飞书消息 ID

    Returns:
        bool: 更新成功返回 True；缓存未命中返回 False
    """
    card_body = _pop_cached_card(message_id)
    if card_body is None:
        logger.warning(f"未找到卡片缓存 message_id={message_id}，可能是服务重启导致，跳过卡片更新")
        return False

    # 修改 header
    if "header" in card_body:
        header = card_body["header"]
        if "title" in header:
            header["title"]["content"] = header["title"]["content"].replace(
                "待审批：", "✅ 已批准："
            )
        header["template"] = "green"

    # 移除 action buttons，替换为只读状态标记
    _replace_card_actions(card_body, "✅ **已批准**")
    return _update_card(message_id, card_body)


def update_card_rejected(message_id: str, reject_reason: str = "") -> bool:
    """更新卡片为「已拒绝」状态（从缓存取出原卡片 JSON 修改后推送更新）。

    Args:
        message_id:   飞书消息 ID
        reject_reason: 拒绝原因

    Returns:
        bool: 更新成功返回 True；缓存未命中返回 False
    """
    card_body = _pop_cached_card(message_id)
    if card_body is None:
        logger.warning(f"未找到卡片缓存 message_id={message_id}，可能是服务重启导致，跳过卡片更新")
        return False

    # 修改 header
    if "header" in card_body:
        header = card_body["header"]
        if "title" in header:
            header["title"]["content"] = header["title"]["content"].replace(
                "待审批：", "❌ 已拒绝："
            )
        header["template"] = "red"

    # 替换 action buttons 为只读状态标记
    status_text = "❌ **已拒绝**"
    if reject_reason:
        status_text += f"\n原因：{reject_reason}"
    _replace_card_actions(card_body, status_text)
    return _update_card(message_id, card_body)


def send_binding_confirm_card(
    *,
    chat_id: str,
    employee_id: str,
    employee_name: str,
    department: str,
    position: str,
) -> bool:
    """发送身份绑定确认卡片（用 chat_id，因为此时尚未绑定 open_id）。

    按钮 value 携带绑定所需全部数据，回调时不依赖内存状态。
    """
    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "🔐 身份绑定确认"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**姓名：**{employee_name}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**部门：**{department}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**职位：**{position}"},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**工号：**{employee_id}"},
            },
            {
                "tag": "hr",
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "确认绑定此身份？绑定后可使用 HR 功能。"},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 确认绑定"},
                        "type": "primary",
                        "value": json.dumps({
                            "action": "confirm_binding",
                            "employee_id": employee_id,
                            "employee_name": employee_name,
                            "chat_id": chat_id,
                        }),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 取消"},
                        "type": "default",
                        "value": json.dumps({
                            "action": "cancel_binding",
                            "chat_id": chat_id,
                        }),
                    },
                ],
            },
        ],
    }

    return _send_card_to_chat(chat_id, card)


def update_binding_card_confirmed(message_id: str) -> bool:
    """更新绑定卡片为「已确认」状态。"""
    card_body = _pop_cached_card(message_id)
    if card_body is None:
        return False

    if "header" in card_body:
        card_body["header"]["title"]["content"] = "✅ 绑定成功"
        card_body["header"]["template"] = "green"

    _replace_card_actions(card_body, "✅ **绑定成功** — 现在可以使用 HR 功能了")
    return _update_card(message_id, card_body)


def update_binding_card_cancelled(message_id: str) -> bool:
    """更新绑定卡片为「已取消」状态。"""
    card_body = _pop_cached_card(message_id)
    if card_body is None:
        return False

    if "header" in card_body:
        card_body["header"]["title"]["content"] = "❌ 已取消"
        card_body["header"]["template"] = "red"

    _replace_card_actions(card_body, "❌ **已取消绑定** — 需要时可重新输入工号")
    return _update_card(message_id, card_body)


def send_notification(open_id: str, text: str) -> bool:
    """给指定用户发送文本通知（单聊消息）。

    Args:
        open_id: 接收者的飞书 open_id（ou_xxx）
        text:    通知文本

    Returns:
        bool: 发送成功返回 True
    """
    token = get_tenant_access_token()
    url = f"{FEISHU_BASE}/im/v1/messages"

    body = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    params = {"receive_id_type": "open_id"}

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            params=params,
            json=body,
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"发送通知失败: code={data.get('code')} msg={data.get('msg')}")
            return False
        logger.info(f"通知已发送到 {open_id}")
        return True
    except Exception as e:
        logger.error(f"发送通知网络异常: {e}")
        return False


# ── 内部辅助 ──

def _send_card(open_id: str, card: dict) -> bool:
    """发送卡片消息到指定 open_id，发送成功后自动缓存卡片 JSON。"""
    return _send_card_impl(open_id, card, "open_id")


def _send_card_to_chat(chat_id: str, card: dict) -> bool:
    """发送卡片消息到指定 chat_id（用于尚未绑定 open_id 的场景）。"""
    return _send_card_impl(chat_id, card, "chat_id")


def _send_card_impl(receive_id: str, card: dict, id_type: str) -> bool:
    """发送卡片消息的内部实现。"""
    token = get_tenant_access_token()
    url = f"{FEISHU_BASE}/im/v1/messages"

    body = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }
    params = {"receive_id_type": id_type}

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            params=params,
            json=body,
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"发送卡片失败: code={data.get('code')} msg={data.get('msg')}")
            return False
        message_id = data.get("data", {}).get("message_id", "")
        if message_id:
            _cache_card(message_id, card)
        logger.info(f"卡片已发送到 {id_type}={receive_id}, message_id={message_id}")
        return True
    except Exception as e:
        logger.error(f"发送卡片网络异常: {e}")
        return False


def _replace_card_actions(card_body: dict, text: str):
    """将卡片中的 action buttons 替换为只读文本。"""
    new_elements = []
    for el in card_body.get("elements", []):
        if el.get("tag") == "action":
            new_elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": text},
            })
        else:
            new_elements.append(el)
    card_body["elements"] = new_elements


def _update_card(message_id: str, card: dict) -> bool:
    """更新已发送的卡片消息（PATCH 方式替换内容）。"""
    token = get_tenant_access_token()
    url = f"{FEISHU_BASE}/im/v1/messages/{message_id}"

    try:
        resp = requests.patch(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"content": json.dumps(card)},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"更新卡片失败: code={data.get('code')} msg={data.get('msg')}")
            return False
        logger.info(f"卡片已更新: {message_id}")
        return True
    except Exception as e:
        logger.error(f"更新卡片网络异常: {e}")
        return False
