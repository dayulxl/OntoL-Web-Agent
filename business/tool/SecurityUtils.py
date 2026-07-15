"""
AES 加解密工具 — 最简常量封装
==============================
纯工具，无业务依赖，跨域引用。

    from business.tool.SecurityUtils import aes_encrypt, aes_decrypt

    cipher = aes_encrypt("hello")
    plain  = aes_decrypt(cipher)
"""
from cryptography.fernet import Fernet

# ═══════════════════════════════════════════════════════════════
# 加解密常量 — 生产环境应替换为环境变量注入
# ═══════════════════════════════════════════════════════════════

_KEY = b"SolvAGz88JG_zVJDZ3fsz5Vuo1zgQ84re0S_R0x5HNo="

_cipher = Fernet(_KEY)


def aes_encrypt(plain: str) -> str:
    """AES 加密 — str → str。"""
    return _cipher.encrypt(plain.encode("utf-8")).decode("utf-8")


def aes_decrypt(cipher: str) -> str:
    """AES 解密 — str → str。"""
    return _cipher.decrypt(cipher.encode("utf-8")).decode("utf-8")
