"""Cursor pagination shared by authenticated message projections."""

import base64
import json

from fastapi import HTTPException

from services import supabase_client


def decode_message_cursor(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))
        return str(payload["created_at"]), int(payload["id"])
    except Exception as exc:
        raise HTTPException(400, detail="Cursor de mensagens invalido.") from exc


def encode_message_cursor(row: dict | None) -> str | None:
    if not row or row.get("id") is None or not row.get("created_at"):
        return None
    raw = json.dumps(
        {"created_at": row["created_at"], "id": row["id"]}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def message_page(
    lead_ref: int, *, limit: int, after: str | None, before: str | None,
) -> dict:
    if after and before:
        raise HTTPException(400, detail="Use apenas um cursor: before ou after.")
    after_created_at, after_id = decode_message_cursor(after)
    before_created_at, before_id = decode_message_cursor(before)
    rows = supabase_client.get_messages_page(
        lead_ref,
        limit=limit,
        after_created_at=after_created_at,
        after_id=after_id,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit] if after else rows[-limit:]
    return {
        "items": rows,
        "before_cursor": encode_message_cursor(rows[0] if rows else None) or before,
        "after_cursor": encode_message_cursor(rows[-1] if rows else None) or after,
        "next_cursor": encode_message_cursor(rows[-1] if rows else None) or after,
        "has_more": has_more,
    }
