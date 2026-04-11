"""Transparent field encryption for sensitive settings values."""

import json
import os
from base64 import b64decode, b64encode
from functools import lru_cache

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.types import Text, TypeDecorator

from config import SECRET_KEY_FILE


_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _load_secret_key():
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")

    try:
        if os.path.exists(SECRET_KEY_FILE):
            with open(SECRET_KEY_FILE, "rb") as handle:
                file_key = handle.read().strip()
                if file_key:
                    return file_key
    except OSError:
        return None
    return None


def _derive_key(salt):
    secret_key = _load_secret_key()
    if not secret_key:
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    return kdf.derive(secret_key)


def encrypt_field_value(value):
    if value in (None, ""):
        return value
    if not isinstance(value, str):
        value = str(value)
    if value.startswith(_PREFIX):
        return value

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(salt)
    if not key:
        return value

    ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
    payload = {
        "s": b64encode(salt).decode("utf-8"),
        "n": b64encode(nonce).decode("utf-8"),
        "c": b64encode(ciphertext).decode("utf-8"),
    }
    return _PREFIX + b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def decrypt_field_value(value):
    if value in (None, "") or not isinstance(value, str):
        return value
    if not value.startswith(_PREFIX):
        return value

    encoded_payload = value[len(_PREFIX):]
    try:
        payload = json.loads(b64decode(encoded_payload.encode("utf-8")).decode("utf-8"))
        salt = b64decode(payload["s"].encode("utf-8"))
        nonce = b64decode(payload["n"].encode("utf-8"))
        ciphertext = b64decode(payload["c"].encode("utf-8"))
        key = _derive_key(salt)
        if not key:
            return value
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception:
        return value


class EncryptedString(TypeDecorator):
    """SQLAlchemy type that transparently encrypts/decrypts string data."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_field_value(value)

    def process_result_value(self, value, dialect):
        return decrypt_field_value(value)
