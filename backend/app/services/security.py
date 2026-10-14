"""Authentication helpers and protected token/session primitives."""
import base64
import hashlib
import hmac
import os
import secrets
from urllib.parse import unquote, urlsplit, urlunsplit

from itsdangerous import URLSafeTimedSerializer

SESSION_SECRET = os.getenv("KODO_SESSION_SECRET", "local-only-change-this-secret")
if os.getenv("ENVIRONMENT", "development").lower() == "production" and SESSION_SECRET == "local-only-change-this-secret":
    raise RuntimeError("KODO_SESSION_SECRET must be set in production")
serializer = URLSafeTimedSerializer(SESSION_SECRET)

def _cookie_secure() -> bool:
    configured = os.getenv("KODO_COOKIE_SECURE")
    return configured.lower() == "true" if configured is not None else os.getenv("ENVIRONMENT", "development").lower() == "production"

def _safe_app_return_path(value: str | None) -> str | None:
    if not value or len(value) > 2048 or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        decoded_path = unquote(parsed.path)
    except ValueError:
        return None
    segments = decoded_path.split("/")
    if parsed.scheme or parsed.netloc or not (decoded_path == "/app" or decoded_path.startswith("/app/")):
        return None
    if any(segment in {".", ".."} for segment in segments):
        return None
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"

def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = password_hash.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

def _cipher():
    from cryptography.fernet import Fernet
    import base64
    secret = os.getenv("KODO_SESSION_SECRET", "local-only-change-this-secret").encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))

def _encrypt_token(token: str) -> str:
    return _cipher().encrypt(token.encode()).decode()

def _decrypt_token(token: str) -> str:
    return _cipher().decrypt(token.encode()).decode()
