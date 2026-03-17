import base64
import hashlib
import hmac
import json
import secrets
import time

from ..config import get_settings


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))


def _sign(payload: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(signature)


def issue_session_token(session_id: str) -> str:
    settings = get_settings()
    now = int(time.time())
    claims = {
        "sid": session_id,
        "iat": now,
        "exp": now + settings.SESSION_TOKEN_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    payload = _b64url_encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _sign(payload, settings.SESSION_TOKEN_SECRET)
    return f"{payload}.{signature}"


def verify_session_token(session_id: str, token: str) -> bool:
    settings = get_settings()
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return False

    expected = _sign(payload_b64, settings.SESSION_TOKEN_SECRET)
    if not hmac.compare_digest(signature, expected):
        return False

    try:
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False

    if claims.get("sid") != session_id:
        return False
    now = int(time.time())
    exp = int(claims.get("exp", 0))
    return exp >= now
