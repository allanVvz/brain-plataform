"""Brain edge gateway for the microservice cutover.

This app is deployed independently from the legacy ``main:app``. It owns the
browser cookie boundary, removes client identity headers, and emits a short
HMAC-signed principal to private upstreams.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Brain Gateway", version="1.0.0")

IDENTITY_HEADERS = {"x-brain-principal", "x-brain-principal-signature"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
PUBLIC_PREFIXES = ("/health", "/auth/", "/webhooks/", "/api/menu/")
UPSTREAM_ENVIRONMENTS = {
    "control-plane": "BRAIN_CONTROL_PLANE_URL",
    "conversation-runtime": "BRAIN_RUNTIME_URL",
    "transport": "BRAIN_TRANSPORT_URL",
}


def _build_payload(*, ready: bool, dependencies: dict | None = None) -> dict:
    payload = {
        "service": "brain-gateway",
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "source_sha": (os.environ.get("SOURCE_SHA") or "0" * 40).strip(),
        "build_digest": (os.environ.get("BUILD_DIGEST") or "unknown").strip(),
        "contracts_version": (os.environ.get("BRAIN_CONTRACTS_VERSION") or "1.0.0").strip(),
        "required_schema_version": int(os.environ.get("REQUIRED_SCHEMA_VERSION") or "131"),
        "slot": (os.environ.get("BRAIN_SLOT") or "unknown").strip(),
    }
    if dependencies is not None:
        payload["dependencies"] = dependencies
    return payload


@app.get("/health")
async def health() -> dict:
    return _build_payload(ready=True)


@app.get("/health/ready")
async def readiness() -> Response:
    dependencies: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for service, environment in UPSTREAM_ENVIRONMENTS.items():
            base_url = (os.environ.get(environment) or "").rstrip("/")
            if not base_url:
                dependencies[service] = {"ready": False, "error": "url_not_configured"}
                continue
            try:
                response = await client.get(f"{base_url}/health/ready")
                is_json = response.headers.get("content-type", "").startswith("application/json")
                body = response.json() if is_json else {}
                dependencies[service] = {
                    "ready": response.status_code == 200 and (
                        body.get("ready") is True or body.get("status") == "ready"
                    ),
                    "status_code": response.status_code,
                    "source_sha": body.get("source_sha") or body.get("build_sha"),
                    "build_digest": body.get("build_digest") or body.get("image_digest"),
                    "contracts_version": body.get("contracts_version"),
                    "schema_version": body.get("schema_version"),
                }
            except httpx.HTTPError as exc:
                dependencies[service] = {"ready": False, "error": type(exc).__name__}
    ready = all(item.get("ready") is True for item in dependencies.values())
    payload = _build_payload(ready=ready, dependencies=dependencies)
    return JSONResponse(payload, status_code=200 if ready else 503)


def _upstream(path: str) -> str:
    if path.startswith(("/webhooks/evolution/", "/webhooks/whatsapp", "/messages")):
        return os.environ["BRAIN_TRANSPORT_URL"]
    if path.startswith(("/process", "/agents", "/agent-harness", "/insights", "/leads", "/wa-validator", "/qa/")):
        return os.environ["BRAIN_RUNTIME_URL"]
    return os.environ["BRAIN_CONTROL_PLANE_URL"]


def _principal(session: dict) -> tuple[str, str]:
    secret = (os.environ.get("BRAIN_INTERNAL_AUTH_SECRET") or "").encode()
    if len(secret) < 32:
        raise RuntimeError("BRAIN_INTERNAL_AUTH_SECRET must contain at least 32 bytes")
    user = session.get("user") or {}
    now = int(time.time())
    claims = {
        "iss": "brain-gateway", "sub": str(user.get("id") or ""),
        "role": str(user.get("role") or "viewer"),
        "email": user.get("email"), "username": user.get("username"),
        "persona_ids": [str(row.get("id")) for row in session.get("personas") or [] if row.get("id")],
        "iat": now, "exp": now + 60, "nonce": uuid.uuid4().hex,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    return encoded, hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()


def _headers(request: Request) -> dict[str, str]:
    return {
        key: value for key, value in request.headers.items()
        if key.lower() not in IDENTITY_HEADERS | HOP_HEADERS | {"cookie"}
    }


async def _session(request: Request) -> dict | None:
    control = os.environ["BRAIN_CONTROL_PLANE_URL"].rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{control}/auth/me", headers={"cookie": request.headers.get("cookie", "")})
    return response.json() if response.status_code == 200 else None


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(path: str, request: Request) -> Response:
    route = "/" + path
    if route.startswith("/api-brain/"):
        route = route.removeprefix("/api-brain")
    if route.startswith("/internal/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    headers = _headers(request)
    is_public = route == "/" or route.startswith(PUBLIC_PREFIXES)
    if not is_public:
        session = await _session(request)
        if not session:
            return JSONResponse({"detail": "Sessao obrigatoria."}, status_code=401)
        principal, signature = _principal(session)
        headers["x-brain-principal"] = principal
        headers["x-brain-principal-signature"] = signature
    elif route.startswith("/auth/"):
        headers["cookie"] = request.headers.get("cookie", "")
    target = _upstream(route).rstrip("/") + route
    body = await request.body()
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        upstream = await client.request(request.method, target, params=request.query_params,
                                        content=body, headers=headers)
    response_headers = {
        key: value for key, value in upstream.headers.items()
        if key.lower() not in HOP_HEADERS
    }
    return Response(upstream.content, status_code=upstream.status_code,
                    headers=response_headers, media_type=upstream.headers.get("content-type"))
