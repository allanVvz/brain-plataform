import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

from fastapi import HTTPException, Request, Response

from services import supabase_client

SESSION_COOKIE = "ai_brain_session"
HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 390000
SESSION_TTL_SECONDS = 12 * 60 * 60
REMEMBER_TTL_SECONDS = 30 * 24 * 60 * 60


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _auth_secret() -> bytes:
    secret = os.environ.get("AI_BRAIN_AUTH_SECRET") or os.environ.get("NEXTAUTH_SECRET")
    if not secret:
        secret = "dev-only-ai-brain-auth-secret-change-me"
    return secret.encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ITERATIONS)
    return f"{HASH_ALGORITHM}${HASH_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != HASH_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _safe_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "username": row.get("username"),
        "name": row.get("name"),
        "role": row.get("role") or "user",
        "is_active": bool(row.get("is_active", True)),
    }


def get_user_by_identifier(identifier: str) -> Optional[dict[str, Any]]:
    ident = (identifier or "").strip().lower()
    if not ident:
        return None
    client = supabase_client.get_client()
    fields = "id,email,username,password_hash,name,role,is_active"
    result = client.table("app_users").select(fields).eq("email", ident).limit(1).execute()
    rows = result.data or []
    if rows:
        return rows[0]
    result = client.table("app_users").select(fields).eq("username", ident).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    result = (
        supabase_client.get_client()
        .table("app_users")
        .select("id,email,username,name,role,is_active")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data


def get_user_access(user_id: str) -> list[dict[str, Any]]:
    result = (
        supabase_client.get_client()
        .table("user_persona_access")
        .select("id,user_id,client_id,persona_id,persona_slug,can_view,can_edit,can_manage")
        .eq("user_id", user_id)
        .eq("can_view", True)
        .execute()
    )
    return result.data or []


def get_session_payload(token: str) -> Optional[dict[str, Any]]:
    try:
        payload_raw, signature = token.split(".", 1)
        expected = _b64encode(hmac.new(_auth_secret(), payload_raw.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64decode(payload_raw).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def create_session_token(user: dict[str, Any], remember: bool = False) -> tuple[str, int]:
    now = int(time.time())
    ttl = REMEMBER_TTL_SECONDS if remember else SESSION_TTL_SECONDS
    payload = {
        "sub": user["id"],
        "email": user.get("email"),
        "role": user.get("role") or "user",
        "iat": now,
        "exp": now + ttl,
    }
    payload_raw = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64encode(hmac.new(_auth_secret(), payload_raw.encode("ascii"), hashlib.sha256).digest())
    return f"{payload_raw}.{signature}", ttl


def set_session_cookie(response: Response, token: str, ttl: int) -> None:
    secure = (os.environ.get("AI_BRAIN_COOKIE_SECURE") or "").lower() in {"1", "true", "yes"}
    if (os.environ.get("ENVIRONMENT") or os.environ.get("NODE_ENV") or "").lower() == "production":
        secure = True
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax")


def authenticate(identifier: str, password: str) -> dict[str, Any]:
    row = get_user_by_identifier(identifier)
    if not row or not verify_password(password, row.get("password_hash") or ""):
        raise HTTPException(status_code=401, detail="Email/usuario ou senha invalidos.")
    if not row.get("is_active", True):
        raise HTTPException(status_code=403, detail="Usuario inativo. Fale com um administrador.")
    return _safe_user(row)


def is_admin(user: Optional[dict[str, Any]]) -> bool:
    return bool(user and user.get("role") == "admin")


def current_user(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Sessao obrigatoria.")
    return user


def allowed_access(request: Request) -> list[dict[str, Any]]:
    return list(getattr(request.state, "persona_access", []) or [])


def allowed_persona_ids(request: Request) -> list[str]:
    if is_admin(getattr(request.state, "user", None)):
        return []
    return [row["persona_id"] for row in allowed_access(request) if row.get("persona_id")]


def assert_persona_access(request: Request, persona_id: Optional[str] = None, persona_slug: Optional[str] = None) -> None:
    user = current_user(request)
    if is_admin(user):
        return
    access = allowed_access(request)
    if not access:
        raise HTTPException(status_code=403, detail="Nenhuma persona foi atribuida a este usuario.")
    if persona_id and any(row.get("persona_id") == persona_id for row in access):
        return
    if persona_slug and any(row.get("persona_slug") == persona_slug for row in access):
        return
    raise HTTPException(status_code=403, detail="Acesso negado para esta persona.")


def filter_personas_for_user(user: dict[str, Any], personas: list[dict[str, Any]], access: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if is_admin(user):
        return personas
    allowed = {row.get("persona_id") for row in access}
    allowed_slugs = {row.get("persona_slug") for row in access if row.get("persona_slug")}
    return [p for p in personas if p.get("id") in allowed or p.get("slug") in allowed_slugs]


def build_session_response(user: dict[str, Any]) -> dict[str, Any]:
    personas = supabase_client.get_personas() or []
    access = [] if is_admin(user) else get_user_access(user["id"])
    visible_personas = filter_personas_for_user(user, personas, access)
    if not is_admin(user) and not visible_personas:
        raise HTTPException(status_code=403, detail="Nenhuma persona foi atribuida a este usuario.")
    return {
        "user": user,
        "personas": visible_personas,
        "permissions": {
            "role": user.get("role"),
            "persona_access": access,
        },
    }
