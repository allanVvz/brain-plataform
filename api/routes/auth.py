from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from services import auth_service, supabase_client

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    identifier: str
    password: str
    remember: bool = False


@router.post("/login")
def login(body: LoginBody, response: Response):
    try:
        user = auth_service.authenticate(body.identifier, body.password)
        session_payload = auth_service.build_session_response(user)
        token, ttl = auth_service.create_session_token(user, remember=body.remember)
        auth_service.set_session_cookie(response, token, ttl)
    except HTTPException:
        raise
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("auth.login", f"unexpected login failure: {exc}", exc)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Unexpected login failure.")
    try:
        supabase_client.get_client().table("app_users").update({"last_login_at": datetime.now(timezone.utc).isoformat()}).eq("id", user["id"]).execute()
    except Exception:
        pass
    return session_payload


@router.get("/me")
def me(request: Request):
    user = auth_service.current_user(request)
    return auth_service.build_session_response(user)


@router.post("/logout")
def logout(response: Response):
    auth_service.clear_session_cookie(response)
    return {"ok": True}
