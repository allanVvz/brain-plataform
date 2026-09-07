"""Transactional draft snapshots stored in the existing system_events ledger."""
from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from services import graph_bundle_draft_ops, graph_compiler_v3, supabase_client


class DraftNotFound(LookupError):
    pass


class DraftConflict(RuntimeError):
    def __init__(self, message: str = "draft_cas_conflict", *, current: dict | None = None):
        self.current = current
        super().__init__(message)


def _fingerprint(value: dict[str, Any]) -> str:
    return graph_compiler_v3.canonical_checksum(value)


def _rows(draft_ref: str) -> list[dict[str, Any]]:
    response = (
        supabase_client.get_client().table("system_events").select("payload,persona_id,created_at")
        .eq("entity_type", "graph_bundle_draft")
        .eq("event_type", "graph_bundle_draft_snapshot")
        .eq("entity_id", draft_ref).order("created_at", desc=True).limit(100).execute()
    )
    return sorted(
        list(response.data or []),
        key=lambda row: int((row.get("payload") or {}).get("revision") or 0),
        reverse=True,
    )


def get(draft_ref: str) -> dict[str, Any]:
    rows = _rows(draft_ref)
    if not rows:
        raise DraftNotFound("graph_bundle_draft_not_found")
    return dict(rows[0].get("payload") or {})


def create_ref(persona_id: str, idempotency_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"brain:graph-draft:{persona_id}:{idempotency_key}"))


def replay_create(
    *, persona_id: str, expected_active_checksum: str,
    reason: str, source: dict[str, Any], idempotency_key: str,
) -> dict[str, Any] | None:
    draft_ref = create_ref(persona_id, idempotency_key)
    try:
        prior = get(draft_ref)
    except DraftNotFound:
        return None
    fingerprint = _fingerprint({
        "persona_id": persona_id,
        "active_publication_id": prior.get("base_publication_id"),
        "active_checksum": expected_active_checksum,
        "reason": reason, "source": source,
    })
    return replay(draft_ref, idempotency_key, fingerprint)


def replay(draft_ref: str, idempotency_key: str, request_fingerprint: str) -> dict[str, Any] | None:
    response = (
        supabase_client.get_client().table("system_events").select("payload")
        .eq("entity_type", "graph_bundle_draft")
        .eq("event_type", "graph_bundle_draft_snapshot")
        .eq("entity_id", draft_ref)
        .eq("payload->>idempotency_key", idempotency_key)
        .limit(1).execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None
    payload = dict(rows[0].get("payload") or {})
    if payload.get("request_fingerprint") != request_fingerprint:
        raise DraftConflict("draft_idempotency_key_reused", current=get(draft_ref))
    return payload


def find_open(persona_id: str) -> dict[str, Any] | None:
    response = (
        supabase_client.get_client().table("system_events").select("payload,created_at")
        .eq("entity_type", "graph_bundle_draft")
        .eq("event_type", "graph_bundle_draft_snapshot")
        .eq("persona_id", persona_id).order("created_at", desc=True).limit(1000).execute()
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        ref = str(payload.get("draft_ref") or "")
        if ref and ref not in latest:
            latest[ref] = payload
    return next((row for row in latest.values() if row.get("state") == "draft"), None)


def _commit(
    *, draft_ref: str, persona_id: str, expected_revision: int,
    expected_checksum: str, snapshot: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = supabase_client.get_client().rpc(
            "commit_graph_bundle_draft_snapshot",
            {
                "p_draft_ref": draft_ref, "p_persona_id": persona_id,
                "p_expected_revision": expected_revision,
                "p_expected_checksum": expected_checksum, "p_payload": snapshot,
            },
        ).execute()
    except Exception as exc:
        if "40001" in str(exc) or "CAS conflict" in str(exc) or "already exists" in str(exc):
            raise DraftConflict("draft_cas_conflict") from exc
        raise
    return dict(response.data or snapshot)


def create(
    *, persona_id: str, persona_slug: str, bundle: dict[str, Any],
    active_publication_id: str, active_checksum: str, actor: str,
    reason: str, source: dict[str, Any], idempotency_key: str,
    reuse_open: bool = True,
) -> dict[str, Any]:
    canonical = graph_bundle_draft_ops.canonicalize_draft(bundle)
    checksum = graph_bundle_draft_ops.draft_checksum(canonical)
    draft_ref = create_ref(persona_id, idempotency_key)
    request_fingerprint = _fingerprint({
        "persona_id": persona_id, "active_publication_id": active_publication_id,
        "active_checksum": active_checksum, "reason": reason, "source": source,
    })
    prior = replay(draft_ref, idempotency_key, request_fingerprint)
    if prior:
        return prior
    if reuse_open:
        existing = find_open(persona_id)
        if existing and existing.get("base_publication_id") == active_publication_id:
            return existing
    snapshot = {
        "draft_ref": draft_ref, "persona_id": persona_id, "persona_slug": persona_slug,
        "base_publication_id": active_publication_id, "base_runtime_checksum": active_checksum,
        "revision": 1, "draft_checksum": checksum, "bundle": canonical,
        "state": "draft", "actor": actor, "reason": reason, "source": source,
        "idempotency_key": idempotency_key,
        "request_fingerprint": request_fingerprint,
    }
    return _commit(
        draft_ref=draft_ref, persona_id=persona_id, expected_revision=0,
        expected_checksum="", snapshot=snapshot,
    )


def patch(
    draft_ref: str, *, expected_revision: int, expected_checksum: str,
    operations: list[Any], actor: str, reason: str, source: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    request_fingerprint = _fingerprint({
        "operations": [operation.model_dump(mode="json") for operation in operations],
        "reason": reason, "source": source,
    })
    prior = replay(draft_ref, idempotency_key, request_fingerprint)
    if prior:
        return prior
    current = get(draft_ref)
    if current.get("state") != "draft":
        raise DraftConflict("draft_not_open", current=current)
    candidate, change = graph_bundle_draft_ops.apply_operations_with_cas(
        current["bundle"], actual_revision=int(current["revision"]),
        expected_revision=expected_revision, expected_checksum=expected_checksum,
        operations=operations,
    )
    snapshot = {
        **current, "revision": change["revision"],
        "draft_checksum": change["draft_checksum"], "bundle": candidate,
        "state": "draft", "actor": actor, "reason": reason, "source": source,
        "idempotency_key": idempotency_key, "change_summary": change,
        "request_fingerprint": request_fingerprint,
    }
    return _commit(
        draft_ref=draft_ref, persona_id=current["persona_id"],
        expected_revision=expected_revision, expected_checksum=expected_checksum,
        snapshot=snapshot,
    )
