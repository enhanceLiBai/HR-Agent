"""密码哈希与校验 —— 纯标准库实现，不引入第三方依赖。

使用 PBKDF2-HMAC-SHA256 + 随机盐，迭代 10 万次。
存储格式: hex_salt:hex_key
"""
import hashlib
import os


def hash_password(password: str) -> str:
    """对密码做 PBKDF2 哈希，返回 'salt_hex:key_hex' 字符串。"""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        100_000,
    )
    return salt.hex() + ':' + key.hex()


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码是否与存储的哈希值匹配。"""
    try:
        salt_hex, key_hex = stored.split(':', 1)
        salt = bytes.fromhex(salt_hex)
        stored_key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100_000,
        )
        return new_key == stored_key
    except (ValueError, AttributeError):
        return False
