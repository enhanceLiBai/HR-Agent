"""飞书消息 ↔ Agent 消息格式转换 + 文本消息发送。"""
import re
import json
import logging
import requests
from feishu.auth import get_tenant_access_token

logger = logging.getLogger("feishu.adapter")


def _strip_markdown(text: str) -> str:
    """移除常见 markdown 标记，适配飞书纯文本消息。"""
    # **加粗** → 加粗
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # ### 标题 → 标题
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 表格分隔线 |:---:| 等
    text = re.sub(r'\|[-\s:|]+\|', '', text)
    return text

# ── 飞书 API 基础 URL ──
FEISHU_BASE = "https://open.feishu.cn/open-apis"


def extract_user_message(webhook_body: dict) -> str | None:
    """从飞书 Webhook 请求体中提取用户输入的文本内容。

    飞书事件结构（v2，schema 2.0）:
        {
          "header": {"event_type": "im.message.receive_v1", ...},
          "event": {
            "message": {
              "chat_id": "oc_xxx",
              "message_id": "om_xxx",
              "message_type": "text",           ← v2 字段名
              "content": "{\"text\":\"你好\"}"   ← JSON 字符串
            },
            "sender": {"sender_id": {"open_id": "ou_xxx"}, ...}
          }
        }

    兼容 v1（msg_type）和 v2（message_type）。

    Args:
        webhook_body: 飞书 POST 的完整 JSON

    Returns:
        str | None: 提取出的文本内容。图片/文件等非文本类型返回 None。
    """
    try:
        event = webhook_body.get("event", {})
        message = event.get("message", {})

        if not message:
            return None

        # 飞书 v1 用 msg_type，v2 用 message_type
        msg_type = message.get("msg_type") or message.get("message_type", "")

        if msg_type == "text":
            content_str = message.get("content", "{}")
            content = json.loads(content_str)
            return content.get("text", "").strip()

        # 其他类型暂不支持
        return None
    except Exception as e:
        logger.error(f"提取用户消息失败: {e}")
        return None


def extract_chat_id(webhook_body: dict) -> str | None:
    """从 Webhook 请求体中提取 chat_id。"""
    try:
        return webhook_body.get("event", {}).get("message", {}).get("chat_id")
    except Exception:
        return None


def extract_message_id(webhook_body: dict) -> str | None:
    """从 Webhook 请求体中提取 message_id（用于回复）。"""
    try:
        return webhook_body.get("event", {}).get("message", {}).get("message_id")
    except Exception:
        return None


def extract_open_id(webhook_body: dict) -> str | None:
    """从 Webhook 请求体中提取发送者的 open_id。"""
    try:
        return webhook_body.get("event", {}).get("sender", {}).get("sender_id", {}).get("open_id")
    except Exception:
        return None


def send_text_message(chat_id: str, text: str, root_id: str | None = None) -> bool:
    """发送文本消息到飞书单聊。

    调用飞书「发送消息」API。

    Args:
        chat_id: 飞书会话 ID
        text:    消息文本内容
        root_id: 被回复的消息 ID（可选）

    Returns:
        bool: 发送成功返回 True
    """
    result = _send_message(chat_id, text, root_id)
    return result is not None


def send_initial_message(chat_id: str, text: str = "正在处理…") -> str | None:
    """发送初始占位卡片消息，返回 message_id 供后续流式更新。

    飞书文本消息发送后不可编辑，因此这里用一张简单卡片作为占位，
    后续通过 PATCH 更新卡片内容实现流式效果。
    """
    return _send_card_message(chat_id, text)


def update_message(message_id: str, text: str) -> bool:
    """流式更新占位卡片的内容。

    飞书 PATCH /im/v1/messages/:message_id 只支持卡片消息。
    """
    token = get_tenant_access_token()
    url = f"{FEISHU_BASE}/im/v1/messages/{message_id}"

    text = _strip_markdown(text)
    card = _build_simple_card(text)

    body = {"content": card}

    try:
        resp = requests.patch(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"更新消息失败: code={data.get('code')} msg={data.get('msg')}")
            return False
        return True
    except Exception as e:
        logger.warning(f"更新消息网络异常: {e}")
        return False


# ── 卡片消息辅助 ──

def _build_simple_card(text: str) -> str:
    """构建一张简单卡片，只包含一段文本。"""
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "HR 助手"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": text}}
        ],
    }
    return json.dumps(card, ensure_ascii=False)


def _send_card_message(chat_id: str, text: str) -> str | None:
    """发送一张简单卡片消息，成功返回 message_id。"""
    token = get_tenant_access_token()
    url = f"{FEISHU_BASE}/im/v1/messages"

    text = _strip_markdown(text)
    card = _build_simple_card(text)

    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": card,
    }
    params = {"receive_id_type": "chat_id"}

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
            logger.error(f"发送卡片消息失败: code={data.get('code')} msg={data.get('msg')}")
            return None
        return data.get("data", {}).get("message_id")
    except Exception as e:
        logger.error(f"发送卡片消息网络异常: {e}")
        return None


def _send_message(chat_id: str, text: str, root_id: str | None = None) -> str | None:
    """发送/更新消息的底层函数，成功返回 message_id。"""
    token = get_tenant_access_token()
    url = f"{FEISHU_BASE}/im/v1/messages"

    text = _strip_markdown(text)

    # 飞书消息体最大 15000 字符，超长时只发送前 14000 字符 + 截断提示
    max_len = 14000
    if len(text) > max_len:
        text = text[:max_len] + "\n\n…（内容过长，已截断）"

    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    params = {"receive_id_type": "chat_id"}

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
            logger.error(f"发送消息失败: code={data.get('code')} msg={data.get('msg')}")
            return None
        return data.get("data", {}).get("message_id")
    except Exception as e:
        logger.error(f"发送消息网络异常: {e}")
        return None


def get_message_type_description() -> str:
    """返回不支持的消息类型说明。"""
    return "暂不支持此类消息（如图片、文件等）。请发送文本消息。"
