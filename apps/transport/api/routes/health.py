import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services import supabase_client

router = APIRouter(tags=["health"])
SERVICE_NAME = "brain-transport"
DEFAULT_REQUIRED_SCHEMA_VERSION = 135
REQUIRED_STORAGE_BUCKETS = ("whatsapp-media",)


def _storage_check() -> dict:
    bucket_names: list[str] = []
    accessible: list[str] = []
    errors: dict[str, str] = {}
    try:
        client = supabase_client.get_client()
        rows = client.storage.list_buckets() or []
        bucket_names = sorted(filter(None, (
            row.get("name") if isinstance(row, dict) else getattr(row, "name", None)
            for row in rows
        )))
        for bucket in REQUIRED_STORAGE_BUCKETS:
            if bucket not in bucket_names:
                continue
            try:
                client.storage.from_(bucket).list(path="", options={"limit": 1})
                accessible.append(bucket)
            except Exception as exc:
                errors[bucket] = f"{type(exc).__name__}: {str(exc)[:200]}"
    except Exception as exc:
        errors["list_buckets"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    missing = [bucket for bucket in REQUIRED_STORAGE_BUCKETS if bucket not in bucket_names]
    inaccessible = [bucket for bucket in REQUIRED_STORAGE_BUCKETS if bucket not in accessible and bucket not in missing]
    return {
        "ok": not missing and not inaccessible and not errors,
        "buckets_visible": bucket_names,
        "required": list(REQUIRED_STORAGE_BUCKETS),
        "accessible": accessible,
        "missing": missing,
        "inaccessible": inaccessible,
        "errors": errors,
    }


def _build_metadata() -> dict:
    return {
        "source_sha": (os.environ.get("SOURCE_SHA") or "0" * 40).strip(),
        "build_digest": (os.environ.get("BUILD_DIGEST") or "unknown").strip(),
        "contracts_version": (os.environ.get("BRAIN_CONTRACTS_VERSION") or "3.0.0").strip(),
        "contracts_checksum": (os.environ.get("BRAIN_CONTRACTS_SHA") or "unknown").strip(),
        "slot": (os.environ.get("BRAIN_SLOT") or "unknown").strip(),
    }


@router.get("/")
def root():
    return {"name": "Brain AI", "version": "1.0.0", "status": "ok", "docs": "/docs"}


@router.get("/health")
def health():
    return health_live()


@router.get("/health/live")
def health_live():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        **_build_metadata(),
        "workers_embedded": (os.environ.get("RUN_EMBEDDED_WORKERS") or "").strip().lower() in {"1", "true", "yes", "on"},
    }


@router.get("/health/ready")
def health_ready():
    ok, detail = supabase_client.ping_supabase()
    storage = _storage_check()
    schema_version = int(os.environ.get("CURRENT_SCHEMA_VERSION") or "0")
    required_schema_version = int(
        os.environ.get("REQUIRED_SCHEMA_VERSION") or DEFAULT_REQUIRED_SCHEMA_VERSION
    )
    schema_ok = schema_version >= required_schema_version
    payload = {
        "status": "ready" if ok and schema_ok and storage["ok"] else "not_ready",
        "service": SERVICE_NAME,
        **_build_metadata(),
        "schema_version": schema_version,
        "required_schema_version": required_schema_version,
        "checks": {
            "supabase": {
                "ok": ok,
                "detail": detail,
            },
            "schema": {"ok": schema_ok},
            "storage": storage,
        },
    }
    if ok and schema_ok and storage["ok"]:
        return payload
    return JSONResponse(payload, status_code=503)


@router.get("/health/score")
def health_score():
    history = supabase_client.get_health_history(limit=1)
    latest = history[-1] if history else None
    return latest or {"score_total": 0, "message": "no snapshot yet"}


@router.get("/health/storage")
def health_storage():
    """Diagnostic for /assets/upload: which Supabase project the API actually
    talks to, and whether the required buckets are visible to it.

    Useful when an upload returns "Bucket not found" — this endpoint pins down
    if the API is hitting a different project than expected (env mix-up) or if
    the bucket truly is missing from the right project.
    """
    url = os.environ.get("SUPABASE_URL") or ""
    project_ref = url.replace("https://", "").split(".", 1)[0] if url else None
    payload = {
        "supabase_url": url,
        "project_ref": project_ref,
        **_storage_check(),
    }
    status_code = 200 if payload["ok"] else 503
    return JSONResponse(payload, status_code=status_code)
