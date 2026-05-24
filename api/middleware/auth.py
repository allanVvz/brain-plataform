import os

from fastapi import Request
from fastapi.responses import JSONResponse

from services import auth_service

PUBLIC_EXACT_PATHS = {
    "/",
    "/health",
    "/health/live",
    "/health/ready",
    "/health/score",
    "/health/storage",
    "/auth/login",
    "/auth/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
}

PUBLIC_PREFIXES = (
    "/process",
    "/api/menu",
    "/menu",
)

ADMIN_TOKEN_HEADER = "x-ai-brain-admin-token"
ADMIN_TOKEN_ENV_NAMES = ("QA", "qa", "preview", "PREVIEW", "test", "TEST")


def is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _admin_test_token_user(request: Request) -> dict | None:
    """When ENVIRONMENT is qa/preview, allow a shared X-AI-BRAIN-ADMIN-TOKEN
    header to act as the admin user. Production never accepts this path.

    The token must come from the env var AI_BRAIN_ADMIN_TEST_TOKEN and is
    compared in constant time. The token value itself is never logged.
    """
    env_name = (os.environ.get("ENVIRONMENT") or "").strip()
    if env_name not in ADMIN_TOKEN_ENV_NAMES:
        return None
    expected = (os.environ.get("AI_BRAIN_ADMIN_TEST_TOKEN") or "").strip()
    if not expected:
        return None
    presented = (request.headers.get(ADMIN_TOKEN_HEADER) or "").strip()
    if not presented:
        return None
    # Constant-time compare to avoid timing leaks.
    import hmac

    if not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
        return None
    return {
        "id": "qa-admin-token",
        "email": "qa-admin@token.local",
        "username": "qa-admin",
        "name": "QA Admin (token)",
        "role": "admin",
        "is_active": True,
        "auth_method": "admin_test_token",
    }


async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or is_public_path(request.url.path):
        return await call_next(request)

    token_user = _admin_test_token_user(request)
    if token_user:
        request.state.user = token_user
        request.state.persona_access = []
        return await call_next(request)

    token = request.cookies.get(auth_service.SESSION_COOKIE)
    payload = auth_service.get_session_payload(token or "")
    if not payload:
        return JSONResponse({"detail": "Sessao obrigatoria."}, status_code=401)

    fallback_user = {
        "id": payload.get("sub") or "",
        "email": payload.get("email"),
        "username": payload.get("email"),
        "name": payload.get("email") or payload.get("sub") or "Sessao ativa",
        "role": payload.get("role") or "user",
        "is_active": True,
    }

    try:
        user = auth_service.get_user_by_id(payload.get("sub") or "")
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.warn(
                "auth_middleware",
                f"falling back to signed session payload: {exc}",
                exc,
            )
        except Exception:
            pass
        user = fallback_user if fallback_user["id"] else None

    if not user or not user.get("is_active", True):
        return JSONResponse({"detail": "Sessao invalida."}, status_code=401)

    request.state.user = user
    if auth_service.is_admin(user):
        request.state.persona_access = []
    else:
        try:
            request.state.persona_access = auth_service.get_user_access(user["id"])
        except Exception as exc:
            try:
                from services import sre_logger
                sre_logger.warn(
                    "auth_middleware",
                    f"persona access unavailable, using empty scope: {exc}",
                    exc,
                )
            except Exception:
                pass
            request.state.persona_access = []
    return await call_next(request)
