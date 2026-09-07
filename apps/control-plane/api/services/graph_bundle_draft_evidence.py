"""Durable pre-publication evidence stored in the existing system_events ledger."""
from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from services import supabase_client


class DraftEvidenceError(RuntimeError):
    pass


def _ref(kind: str, draft_ref: str, revision: int, checksum: str, key: str) -> str:
    value = uuid5(
        NAMESPACE_URL,
        f"brain:graph-draft-evidence:{kind}:{draft_ref}:{revision}:{checksum}:{key}",
    )
    return f"{kind}:{value}"


def record(
    kind: str,
    *,
    draft: dict[str, Any],
    result: dict[str, Any],
    actor: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if kind not in {"plan", "validation"}:
        raise ValueError("unsupported draft evidence kind")
    evidence_ref = _ref(
        kind, draft["draft_ref"], int(draft["revision"]),
        draft["draft_checksum"], idempotency_key,
    )
    payload = {
        "evidence_ref": evidence_ref,
        "draft_ref": draft["draft_ref"],
        "revision": draft["revision"],
        "draft_checksum": draft["draft_checksum"],
        "runtime_checksum": result.get("runtime_checksum"),
        "ok": result.get("ok", True),
        "actor": actor,
        "idempotency_key": idempotency_key,
        "result": result,
    }
    client = supabase_client.get_client()
    existing = (
        client.table("system_events").select("payload")
        .eq("entity_type", "graph_bundle_draft_evidence")
        .eq("entity_id", evidence_ref).maybe_single().execute().data
    )
    if existing:
        return dict(existing.get("payload") or {})
    row = {
        "id": evidence_ref.split(":", 1)[1],
        "event_type": f"graph_bundle_draft_{kind}",
        "entity_type": "graph_bundle_draft_evidence",
        "entity_id": evidence_ref,
        "persona_id": draft["persona_id"],
        "payload": payload,
        "level": "info" if payload["ok"] else "warning",
        "source": "services.graph_bundle_draft_evidence",
    }
    try:
        response = client.table("system_events").insert(row).execute()
    except Exception:
        # The deterministic primary key makes concurrent retries converge on
        # the first immutable evidence row instead of creating two proofs.
        existing = (
            client.table("system_events").select("payload")
            .eq("id", row["id"]).maybe_single().execute().data
        )
        if existing:
            return dict(existing.get("payload") or {})
        raise
    if not response.data:
        raise DraftEvidenceError("draft_evidence_not_persisted")
    return payload


def require(
    evidence_ref: str,
    kind: str,
    *,
    draft: dict[str, Any],
    runtime_checksum: str,
) -> dict[str, Any]:
    row = (
        supabase_client.get_client().table("system_events").select("payload,persona_id")
        .eq("entity_type", "graph_bundle_draft_evidence")
        .eq("event_type", f"graph_bundle_draft_{kind}")
        .eq("entity_id", evidence_ref).maybe_single().execute().data
    )
    payload = dict((row or {}).get("payload") or {})
    matches = (
        row
        and str(row.get("persona_id") or "") == str(draft["persona_id"])
        and payload.get("draft_ref") == draft["draft_ref"]
        and payload.get("revision") == draft["revision"]
        and payload.get("draft_checksum") == draft["draft_checksum"]
        and payload.get("runtime_checksum") == runtime_checksum
    )
    if not matches or (kind == "validation" and payload.get("ok") is not True):
        raise DraftEvidenceError("publish_evidence_stale")
    return payload
