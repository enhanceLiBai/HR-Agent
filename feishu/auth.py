"""飞书 Token 管理 + Webhook 验签 + 事件解密。"""
import os
import time
import hashlib
import hmac
import base64
import json
import logging
import requests
from datetime import datetime
from Crypto.Cipher import AES

logger = logging.getLogger("feishu.auth")

# ── 环境变量 ──
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")  # 事件签名 + 解密（官方规范只用这一把钥匙）

# ── Token 缓存 ──
_token_cache: dict = {
    "token": None,
    "expire_at": 0,  # unix timestamp
}


def _sign_debug(msg: str):
    """验签调试日志。"""
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_feishu_sign.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def get_tenant_access_token() -> str:
    """获取 tenant_access_token，自动刷新。

    飞书 tenant_access_token 有效期约 2 小时，
    提前 5 分钟刷新避免边界失效。

    Returns:
        str: tenant_access_token

    Raises:
        RuntimeError: 获取 token 失败
    """
    global _token_cache

    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire_at"] - 300:
        return _token_cache["token"]

    if not APP_ID or not APP_SECRET:
        raise RuntimeError(
            "FEISHU_APP_ID / FEISHU_APP_SECRET 未配置。"
            "请在 .env 中设置后重启服务。"
        )

    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
            timeout=10,
        )
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"获取 tenant_access_token 网络异常: {e}")

    if data.get("code") != 0:
        raise RuntimeError(
            f"获取 tenant_access_token 失败: code={data.get('code')} "
            f"msg={data.get('msg')}"
        )

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = now + data.get("expire", 7200)
    logger.info("tenant_access_token 已刷新")
    return _token_cache["token"]


def verify_webhook_signature(timestamp: str, nonce: str, body: str, signature: str) -> bool:
    """验证飞书 Webhook 请求签名。

    飞书事件签名算法（官方规范）:
      SHA256(timestamp + nonce + encrypt_key + 原始请求体 JSON 字符串)
    注意：是纯 SHA256 拼接，不是 HMAC。

    Args:
        timestamp: 请求头中的 X-Lark-Request-Timestamp
        nonce:     请求头中的 X-Lark-Request-Nonce
        body:      原始请求体 JSON 字符串（raw bytes decode，不能是 parse 后 re-serialize）
        signature: 请求头中的 X-Lark-Signature

    Returns:
        bool: 签名是否有效
    """
    # 基础校验
    if not signature or not nonce or not timestamp:
        _sign_debug(f"FAIL: 缺少必要头 — ts={bool(timestamp)} nonce={bool(nonce)} sig={bool(signature)}")
        return False

    if not ENCRYPT_KEY:
        logger.warning("FEISHU_ENCRYPT_KEY 未配置，跳过验签")
        _sign_debug("SKIP: ENCRYPT_KEY 未配置")
        return True

    # 时间戳容错（60 秒）
    try:
        ts = int(timestamp)
        now = int(time.time())
        diff = abs(now - ts)
        if diff > 60:
            _sign_debug(f"FAIL: 时间戳过期 — now={now} ts={ts} diff={diff}s")
            return False
        _sign_debug(f"OK: timestamp={ts} diff={diff}s")
    except ValueError:
        _sign_debug(f"WARN: 时间戳无法解析为整数: {timestamp!r}")

    # 拼接 → SHA256（非 HMAC）
    content = f"{timestamp}{nonce}{ENCRYPT_KEY}{body}"
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest().lower()

    if not hmac.compare_digest(expected, signature.lower()):
        _sign_debug(
            f"FAIL: 签名不匹配 — expected={expected[:16]}... "
            f"got={signature[:16].lower()}... "
            f"body_len={len(body)} body_head={body[:80]!r}"
        )
        return False

    _sign_debug(f"PASS: body_len={len(body)} body_head={body[:60]!r}")
    return True


def decrypt_event(encrypted_body: dict) -> dict | None:
    """解密飞书加密事件。

    飞书事件订阅开启「加密」后，POST body 格式为:
        {"encrypt": "<base64_encoded_ciphertext>"}

    解密算法: AES-256-CBC
        - Key = SHA256(ENCRYPT_KEY)
        - IV  = 密文前 16 字节
        - 填充 = PKCS7

    Args:
        encrypted_body: 飞书 POST 的原始 JSON（含 encrypt 字段）

    Returns:
        dict | None: 解密后的事件 JSON；不包含 encrypt 字段则原样返回
    """
    encrypt_str = encrypted_body.get("encrypt", "")
    if not encrypt_str:
        return encrypted_body  # 未加密，直接返回

    if not ENCRYPT_KEY:
        logger.error("FEISHU_ENCRYPT_KEY 未配置，无法解密事件")
        return None

    try:
        # 1. Base64 解码
        raw = base64.b64decode(encrypt_str)

        # 2. AES-256-CBC 解密
        aes_key = hashlib.sha256(ENCRYPT_KEY.encode()).digest()
        iv = raw[:16]
        ciphertext = raw[16:]

        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        padded = cipher.decrypt(ciphertext)

        # 3. 去除 PKCS7 填充
        pad_len = padded[-1]
        plaintext = padded[:-pad_len]

        # 4. 解析事件 JSON
        event_json = json.loads(plaintext.decode("utf-8"))
        logger.info("飞书事件解密成功")
        return event_json
    except Exception as e:
        logger.error(f"飞书事件解密失败: {e}")
        return None
