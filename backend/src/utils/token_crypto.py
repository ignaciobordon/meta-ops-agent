"""
AES-256-GCM token encryption for Meta access tokens.
Key: META_TOKEN_ENCRYPTION_KEY (base64url-encoded 32-byte key from env).
Separate from JWT_SECRET to allow independent rotation.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.src.config import settings


def _get_key() -> bytes:
    """Load the AES-256 key from centralized settings. Raises if missing/invalid."""
    key_b64 = settings.META_TOKEN_ENCRYPTION_KEY or ""
    if not key_b64:
        raise ValueError(
            "META_TOKEN_ENCRYPTION_KEY not set. "
            'Generate with: python -c "import secrets, base64; '
            'print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"'
        )
    key_bytes = base64.urlsafe_b64decode(key_b64)
    if len(key_bytes) != 32:
        raise ValueError(
            f"META_TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes, got {len(key_bytes)}"
        )
    return key_bytes


def encrypt_token(plaintext: str) -> str:
    """
    Encrypt a token string using AES-256-GCM.
    Returns: base64url-encoded string of (nonce || ciphertext || tag).
    Nonce is 12 bytes, generated fresh each call.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce, recommended for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # ciphertext includes the 16-byte GCM tag appended by cryptography library
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_token(encrypted_b64: str) -> str:
    """
    Decrypt a token encrypted with encrypt_token().
    Input: base64url-encoded string of (nonce || ciphertext || tag).
    Returns: plaintext token string.
    Raises on tampered/corrupted data (GCM authentication failure).
    """
    key = _get_key()
    raw = base64.urlsafe_b64decode(encrypted_b64)
    if len(raw) < 28:  # 12 (nonce) + 16 (min tag)
        raise ValueError("Encrypted token data too short (corrupted?)")
    nonce = raw[:12]
    ciphertext = raw[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
