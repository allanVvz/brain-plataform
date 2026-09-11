"""Per-item journal inside the one proof-owned response buffer.

The row lease and payload compare-and-swap protect every provider attempt.
A started item without a persisted receipt is uncertain and never resent.
"""
from copy import deepcopy
import json

import httpx
from services import supabase_client


class ReconciliationRequired(RuntimeError):
    pass


def send_items(items, *, response_id, journal, persist, send, authorize):
    journal = deepcopy(journal)
    for index, item in enumerate(items):
        key = f"{response_id}:item:{index}"
        previous = journal.get(key) or {}
        if previous.get("status") == "completed":
            continue
        if previous.get("status") == "started":
            raise ReconciliationRequired(f"media_item_uncertain:{key}")
        authorize(item)
        journal[key] = {"status": "started", "asset_node_id": item.get("asset_node_id")}
        persist(journal)
        receipt = send(item)
        external_id = ((receipt.get("key") or {}).get("id")
                       or ((receipt.get("messages") or [{}])[0] or {}).get("id")
                       or receipt.get("messageId") or receipt.get("id"))
        if not external_id:
            raise ReconciliationRequired(f"media_item_receipt_missing:{key}")
        journal[key] = {**journal[key], "status": "completed", "external_message_id": str(external_id)}
        persist(journal)
    return journal


def dispatch(row, *, worker_id, provider, binding, recipient, authorize):
    payload = deepcopy(row.get("payload") or {})
    images = payload.get("catalog_images") or []
    if not isinstance(images, list) or not 1 <= len(images) <= 3:
        raise ValueError("catalog_image_limit")
    items = [{"text": str(payload.get("text") or "")}, *images]
    urls = {}

    def check(item):
        # Recheck the committed proof and active publication before every send.
        approved = authorize()
        if approved.get("images") != images:
            raise ValueError("catalog_images_changed")
        if item.get("asset_node_id"):
            if not item.get("bucket") or not item.get("path"):
                raise ValueError("catalog_storage_reference_required")
            url = supabase_client._storage_signed_url(item["bucket"], item["path"], 3600)
            if not url:
                raise ValueError("catalog_media_unavailable")
            response = httpx.head(url, timeout=10, follow_redirects=False)
            response.raise_for_status()
            urls[item["asset_node_id"]] = url

    def persist(journal):
        nonlocal payload
        updated = {**payload, "item_journal": deepcopy(journal)}
        rows = (supabase_client.get_client().table("lead_buffer").update({"payload": updated})
                .eq("id", row["id"]).eq("locked_by", worker_id)
                .eq("payload", json.dumps(payload, ensure_ascii=False)).execute().data)
        if not rows:
            raise ReconciliationRequired("catalog_response_lease_or_revision_changed")
        payload = updated

    def send(item):
        if not item.get("asset_node_id"):
            return provider.send_text(binding, recipient, item["text"])
        return provider.send_media(binding, recipient, {"mediatype": "image", "mimetype": item.get("mime") or "image/jpeg",
            "media": urls[item["asset_node_id"]], "caption": item.get("caption") or ""})

    try:
        journal = send_items(items, response_id=row["id"], journal=payload.get("item_journal") or {},
                            persist=persist, send=send, authorize=check)
    except Exception:
        # The durable started marker also covers a process crash. No provider
        # result is inferred from a network exception or a failed DB commit.
        supabase_client.complete_whatsapp_buffer(row["id"], "waiting_human",
                                               error="catalog_response_requires_reconciliation")
        raise
    return journal[f"{row['id']}:item:0"]["external_message_id"]
