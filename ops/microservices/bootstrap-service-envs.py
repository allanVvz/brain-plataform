#!/usr/bin/env python3
"""Create least-privilege production env files without printing secrets."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".env.compose"
TARGET_DIR = ROOT / ".env.microservices"

COMMON = {
    "ENV", "PYTHON_ENV", "ENVIRONMENT", "SUPABASE_URL", "SUPABASE_PUBLIC_URL",
    "SUPABASE_SSL_VERIFY", "SUPABASE_HTTP_TIMEOUT_SECONDS", "SUPABASE_RETRY_ATTEMPTS",
    "ALLOWED_ORIGINS", "ALLOWED_ORIGIN_REGEX", "AI_BRAIN_CA_BUNDLE",
    "AI_BRAIN_DISABLE_SYSTEM_TRUSTSTORE", "AI_BRAIN_WEBHOOK_TOKEN",
}
CONTROL = COMMON | {
    "AI_BRAIN_AUTH_SECRET", "NEXTAUTH_SECRET", "AI_BRAIN_COOKIE_SECURE",
    "AI_BRAIN_SECRETS_KEY", "AI_BRAIN_PUBLIC_API_URL", "AI_BRAIN_SEED_ADMIN_EMAIL",
    "AI_BRAIN_SEED_ADMIN_USERNAME", "AI_BRAIN_SEED_ADMIN_PASSWORD",
    "AI_BRAIN_SEED_ADMIN_NAME", "AI_BRAIN_SEED_ADMIN_ROLE", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "N8N_BASE_URL", "N8N_API_KEY",
    "DEEPSEEK_CONVERSATION_MODEL", "DEEPSEEK_CONVERSATION_ENDPOINT",
    "GOOGLE_SERVICE_ACCOUNT_JSON", "KB_SPREADSHEET_ID", "KB_SYNC_INTERVAL",
    "N8N_MIRROR_INTERVAL", "FLOW_VALIDATOR_INTERVAL", "HEALTH_CHECK_INTERVAL",
    "GRAPH_RAG_EMBEDDING_PROVIDER", "GRAPH_RAG_EMBEDDING_MODEL",
    "GRAPH_RAG_LOCAL_EMBEDDING_MODEL", "SOFIA_TOOLS_ENABLED",
    "SOFIA_GRAPH_COMMAND_MIN_SCORE", "SOFIA_SHORT_TERM_MEMORY_TTL_SECONDS",
    "SOFIA_SHORT_TERM_MEMORY_MAX_TURNS", "EVOLUTION_ENABLED",
    "BULK_CAMPAIGNS_ROLLOUT1_ENABLED",
}
RUNTIME = COMMON | {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "N8N_BASE_URL",
    "N8N_API_KEY", "DEEPSEEK_CONVERSATION_MODEL", "DEEPSEEK_CONVERSATION_ENDPOINT",
    "GRAPH_RAG_EMBEDDING_PROVIDER", "GRAPH_RAG_EMBEDDING_MODEL",
    "GRAPH_RAG_LOCAL_EMBEDDING_MODEL", "INSECURE_LLM_SSL",
}
TRANSPORT = COMMON | {
    # The transport dispatch worker invokes the canonical n8n conversation
    # workflow for bindings owned by ``n8n_agents``.  Keep the internal n8n
    # base URL in its least-privilege environment so direct-binding validation
    # and dispatch agree on the same endpoint.
    "N8N_BASE_URL",
    "AI_BRAIN_SECRETS_KEY",
    "META_WHATSAPP_ACCESS_TOKEN", "META_WHATSAPP_APP_SECRET", "META_WHATSAPP_VERIFY_TOKEN",
    "EVOLUTION_API_URL", "EVOLUTION_API_KEY",
    "EVOLUTION_ENABLED", "WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE",
    "WHISPER_MAX_AUDIO_SECONDS", "AI_BRAIN_PUBLIC_API_URL",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def mint(secret: str, role: str) -> str:
    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64(json.dumps(
        {"role": role, "iss": "supabase", "iat": now, "exp": now + 10 * 365 * 86400},
        separators=(",", ":"),
    ).encode())
    signature = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def existing_internal_secret() -> str | None:
    for name in ("gateway.env", "control-plane.env", "runtime.env", "transport.env"):
        path = TARGET_DIR / name
        if path.exists():
            value = parse_env(path).get("BRAIN_INTERNAL_AUTH_SECRET")
            if value:
                return value
    return None


def write_env(name: str, allowed: set[str], source: dict[str, str], *, role: str | None,
              jwt_secret: str, internal_secret: str) -> None:
    values = {key: source[key] for key in sorted(allowed) if source.get(key)}
    values.update({
        "ENVIRONMENT": "production",
        "CURRENT_SCHEMA_VERSION": "131",
        "BRAIN_INTERNAL_AUTH_SECRET": internal_secret,
    })
    if role:
        values["BRAIN_DB_JWT"] = mint(jwt_secret, role)
    target = TARGET_DIR / name
    temporary = target.with_suffix(".env.tmp")
    temporary.write_text("".join(f"{key}={value}\n" for key, value in sorted(values.items())), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    print(f"configured {name}: keys={len(values)} role={role or 'none'}")


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(".env.compose is missing")
    source = parse_env(SOURCE)
    # The production Compose stack injects this fixed internal endpoint directly
    # into containers, so it is intentionally absent from .env.compose.
    source.setdefault("SUPABASE_URL", "http://kong:8000")
    jwt_secret = source.get("JWT_SECRET", "")
    if len(jwt_secret) < 32:
        raise SystemExit("JWT_SECRET is missing or too short")
    required = {"SUPABASE_URL", "AI_BRAIN_WEBHOOK_TOKEN"}
    missing = sorted(key for key in required if not source.get(key))
    if not (source.get("AI_BRAIN_AUTH_SECRET") or source.get("NEXTAUTH_SECRET")):
        missing.append("AI_BRAIN_AUTH_SECRET|NEXTAUTH_SECRET")
    if missing:
        raise SystemExit("missing source configuration keys: " + ", ".join(missing))
    TARGET_DIR.mkdir(mode=0o700, exist_ok=True)
    os.chmod(TARGET_DIR, 0o700)
    internal_secret = existing_internal_secret() or secrets.token_urlsafe(48)
    write_env("gateway.env", set(), source, role=None, jwt_secret=jwt_secret, internal_secret=internal_secret)
    write_env("control-plane.env", CONTROL, source, role="brain_control_plane", jwt_secret=jwt_secret,
              internal_secret=internal_secret)
    write_env("runtime.env", RUNTIME, source, role="brain_runtime", jwt_secret=jwt_secret,
              internal_secret=internal_secret)
    transport_allowed = TRANSPORT | {
        key for key in source if key.startswith("EVOLUTION_WEBHOOK_") and key.endswith("_SECRET")
    }
    write_env("transport.env", transport_allowed, source, role="brain_transport", jwt_secret=jwt_secret,
              internal_secret=internal_secret)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
