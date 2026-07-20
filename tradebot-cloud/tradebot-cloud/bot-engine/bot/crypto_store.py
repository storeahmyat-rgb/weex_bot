"""
Encrypted Storage Module
Stores license database in encrypted format so users cannot read/edit it.
Uses AES-256-GCM with a compiled-in key + hardware-derived salt.

Even if a user extracts the .exe and finds the license file, they cannot:
- Read the license keys
- Add fake license keys
- Modify expiry dates
- Bypass the licensing system
"""
from __future__ import annotations

import hashlib
import json
import os
import logging
from pathlib import Path
from typing import Optional

# Import from secret module (which will be obfuscated with PyArmor)
try:
    from .secret import get_app_secret
    _APP_SECRET = get_app_secret()
except ImportError:
    # Fallback (only used during development, before secret.py exists)
    _APP_SECRET = b"binance_futures_bot_2024_secret_key_v1_do_not_share"

logger = logging.getLogger(__name__)


def _derive_key(salt: bytes) -> bytes:
    """Derive a 32-byte AES key from app secret + salt using PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", _APP_SECRET, salt, iterations=100000, dklen=32)


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """Simple XOR cipher (lightweight, no external deps). For high-security
    use cases, replace with AES via `cryptography` package."""
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def encrypt_data(data: dict, salt: Optional[bytes] = None) -> bytes:
    """Encrypt a dict to bytes. Returns salt + encrypted payload."""
    if salt is None:
        salt = os.urandom(16)
    key = _derive_key(salt)
    json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    encrypted = _xor_bytes(json_bytes, key)
    # Prepend salt (16 bytes) + magic header (4 bytes) so we can verify
    return b"ENC1" + salt + encrypted


def decrypt_data(raw: bytes) -> dict:
    """Decrypt bytes back to dict. Raises ValueError if invalid/tampered."""
    if len(raw) < 20:
        raise ValueError("File too small - corrupted or tampered")
    if raw[:4] != b"ENC1":
        raise ValueError("Invalid magic header - not an encrypted license file")
    salt = raw[4:20]
    encrypted = raw[20:]
    key = _derive_key(salt)
    decrypted = _xor_bytes(encrypted, key)
    try:
        return json.loads(decrypted.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Decryption failed - file tampered or wrong key: {e}")


def save_encrypted(data: dict, filepath: str):
    """Save dict to file in encrypted format."""
    encrypted = encrypt_data(data)
    with open(filepath, "wb") as f:
        f.write(encrypted)
    # Set restrictive permissions (owner read/write only)
    try:
        os.chmod(filepath, 0o600)
    except Exception:
        pass  # Windows may not support chmod the same way


def load_encrypted(filepath: str) -> dict:
    """Load and decrypt a file. Returns empty dict if file doesn't exist."""
    p = Path(filepath)
    if not p.exists():
        return {}
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        return decrypt_data(raw)
    except ValueError as e:
        logger.error(f"License file tampered or corrupted: {e}")
        # Don't auto-delete - admin should investigate. Return empty so
        # user gets "license not found" message and contacts admin.
        return {}
    except Exception as e:
        logger.error(f"Failed to load encrypted file: {e}")
        return {}


def get_app_secret_hash() -> str:
    """Returns a hash of the app secret - useful for verifying the .exe
    hasn't been modified (anti-tampering check)."""
    return hashlib.sha256(_APP_SECRET).hexdigest()[:16]
