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

    user = auth_service.get_user_by_id(payload.get("sub") or "")
    if not user or not user.get("is_active", True):
        return JSONResponse({"detail": "Sessao invalida."}, status_code=401)

    request.state.user = user
    request.state.persona_access = [] if auth_service.is_admin(user) else auth_service.get_user_access(user["id"])
    return await call_next(request)
