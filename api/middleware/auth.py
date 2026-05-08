from fastapi import Request
from fastapi.responses import JSONResponse

from services import auth_service

PUBLIC_EXACT_PATHS = {
    "/",
    "/health",
    "/health/score",
    "/auth/login",
    "/auth/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
}

PUBLIC_PREFIXES = (
    "/process",
)


def is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or is_public_path(request.url.path):
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
