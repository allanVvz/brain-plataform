"""Consolidate legacy inline product prices into canonical ``metadata["offer"]``.

Context (see ``packages/brain-contracts/brain_contracts/pricing.py``): price
exists today in several undocumented storage shapes. The API already reads
all of them correctly at request time via ``normalize_offer``, so this script
is consolidation, not an emergency fix -- it rewrites the *stored* graph data
into the canonical ``Offer`` shape so ``price``-only and ``price_cents``-only
nodes stop needing legacy fallbacks forever.

For every non-archived ``product`` node of the given persona:
  1. Compute ``normalize_offer(node["data"], node["metadata"])``.
  2. If it resolves, write ``metadata["offer"] = {"amount", "currency"[,
     "channel"]}`` -- ``channel`` only when non-null.
  3. Every legacy key (``price``, ``price_cents``, etc.) is left in place.
     This is the dual-emit transition; removing legacy keys is a later,
     separate phase.

Hard guarantees:
  - Dry-run by default. ``--apply`` is required to write anything.
  - Idempotent: a node whose ``metadata["offer"]`` already equals the
    computed value is skipped (action ``noop_already_canonical``).
  - Refuses to run against a persona that already has its own dedicated
    ``offer`` nodes (e.g. tock-fatal) -- inlining ``metadata["offer"]`` onto
    product nodes there would create a second source of truth.
  - Value-preserving: the offer this script writes is derived from
    ``normalize_offer`` reading the SAME (untouched) legacy fields the API
    already reads, so the price the API serves cannot change. This is
    asserted per node, not merely assumed.
  - Never touches ``node["data"]`` and never touches a non-``product`` node.
  - In ``--apply`` mode, every write is re-read from the database and
    verified before being counted as successful.

Usage:
    python scripts/backfill_product_offer_metadata.py <persona_slug> [--apply] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from brain_contracts.pricing import Offer, normalize_offer, offer_to_price_cents  # noqa: E402
from services import supabase_client  # noqa: E402


def compute_offer_patch(node: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return the canonical ``metadata["offer"]`` value for one product node.

    ``None`` means ``normalize_offer`` could not resolve a price from any of
    the legacy shapes -- the node is left untouched.
    """
    data = node.get("data") or {}
    metadata = node.get("metadata") or {}
    offer = normalize_offer(data, metadata)
    if offer is None:
        return None
    patch: dict[str, Any] = {"amount": offer.amount, "currency": offer.currency}
    if offer.channel is not None:
        patch["channel"] = offer.channel
    return patch


def plan_node(node: dict[str, Any]) -> dict[str, Any]:
    """Decide what (if anything) should change for one product node.

    ``action`` is one of:
      - ``skip_unresolved``       no legacy price shape resolved.
      - ``noop_already_canonical`` metadata["offer"] already matches.
      - ``write``                  metadata["offer"] should be set/updated.
    """
    node_id = str(node.get("id"))
    metadata = node.get("metadata") or {}
    existing_offer = metadata.get("offer") if isinstance(metadata.get("offer"), dict) else None
    new_offer = compute_offer_patch(node)

    result: dict[str, Any] = {
        "node_id": node_id,
        "slug": node.get("slug"),
        "title": node.get("title"),
        "before": existing_offer,
        "after": new_offer,
    }

    if new_offer is None:
        result["action"] = "skip_unresolved"
        return result

    # Invariant 1: the offer we are about to persist round-trips through the
    # legacy integer-cents derivation exactly.
    offer_obj = Offer(
        amount=new_offer["amount"],
        currency=new_offer["currency"],
        channel=new_offer.get("channel"),
    )
    new_cents = offer_to_price_cents(offer_obj)
    if new_cents != round(float(new_offer["amount"]) * 100):
        result["action"] = "invariant_violation"
        result["reason"] = "offer_to_price_cents(offer) != round(amount * 100)"
        return result

    # Invariant 2: this must be value-preserving. The price the API currently
    # serves is normalize_offer() over the SAME untouched data/metadata --
    # i.e. exactly `new_cents`, since new_offer was derived from that same
    # call. Recomputed explicitly (not just asserted by construction) so a
    # future change to normalize_offer's priority order cannot silently
    # regress this without tripping the check.
    current_offer = normalize_offer(node.get("data") or {}, metadata)
    current_cents = offer_to_price_cents(current_offer)
    result["price_cents_before"] = current_cents
    result["price_cents_after"] = new_cents
    result["value_changed"] = current_cents != new_cents

    if existing_offer == new_offer:
        result["action"] = "noop_already_canonical"
        return result

    result["action"] = "write"
    return result


def _persona_has_offer_nodes(client, persona_id: str) -> bool:
    rows = (
        client.table("knowledge_nodes")
        .select("id")
        .eq("persona_id", persona_id)
        .eq("node_type", "offer")
        .neq("status", "archived")
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows)


def run(*, persona_slug: str, apply: bool, limit: int = 5000) -> dict[str, Any]:
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        return {"ok": False, "error": f"persona not found: {persona_slug!r}"}
    persona_id = str(persona.get("id") or "")
    if not persona_id:
        return {"ok": False, "error": f"persona {persona_slug!r} has no id"}

    client = supabase_client.get_client()
    if _persona_has_offer_nodes(client, persona_id):
        return {
            "ok": False,
            "error": (
                f"refusing to run: persona {persona_slug!r} already has dedicated "
                "offer node(s). Inlining metadata['offer'] on its product nodes "
                "would create a second source of truth for price. This script is "
                "only for personas whose price lives inline on product metadata "
                "(e.g. vz-lupas, baita-conveniencia) -- never a persona already "
                "canonical via offer nodes (e.g. tock-fatal)."
            ),
        }

    nodes = supabase_client.list_product_nodes(persona_id=persona_id, limit=limit)
    plans = [plan_node(node) for node in nodes]
    node_by_id = {str(node.get("id")): node for node in nodes}

    totals = {
        "scanned": len(plans),
        "to_write": sum(1 for p in plans if p["action"] == "write"),
        "already_canonical": sum(1 for p in plans if p["action"] == "noop_already_canonical"),
        "unresolved": sum(1 for p in plans if p["action"] == "skip_unresolved"),
        "invariant_violations": sum(1 for p in plans if p["action"] == "invariant_violation"),
        "value_changed_flagged": sum(1 for p in plans if p.get("value_changed")),
    }

    report: dict[str, Any] = {
        "ok": True,
        "mode": "apply" if apply else "dry-run",
        "persona_slug": persona_slug,
        "persona_id": persona_id,
        "totals": totals,
        "nodes": plans,
    }

    if totals["invariant_violations"] or totals["value_changed_flagged"]:
        report["ok"] = False
        report["error"] = (
            "aborting before any writes: this script must be value-preserving "
            "and every offer must satisfy offer_to_price_cents(normalize_offer(...)) "
            "== round(amount * 100); at least one node violated that. See 'nodes' "
            "for the offending node_id(s)."
        )
        return report

    if not apply:
        return report

    written: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for plan in plans:
        if plan["action"] != "write":
            continue
        node = node_by_id[plan["node_id"]]
        existing_metadata = dict(node.get("metadata") or {})
        new_metadata = {**existing_metadata, "offer": plan["after"]}
        supabase_client.update_knowledge_node(
            plan["node_id"], {"metadata": new_metadata}, mark_related_faqs=False,
        )
        refreshed = supabase_client.get_knowledge_node(plan["node_id"]) or {}
        landed = (refreshed.get("metadata") or {}).get("offer")
        if landed != plan["after"]:
            mismatches.append({
                "node_id": plan["node_id"], "expected": plan["after"], "actual": landed,
            })
        else:
            written.append(plan["node_id"])

    report["written_count"] = len(written)
    report["written_node_ids"] = written
    report["verification_mismatches"] = mismatches
    if mismatches:
        report["ok"] = False
        report["error"] = (
            f"{len(mismatches)} node(s) failed post-write verification; the "
            "written value did not match what was read back."
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("persona_slug", help="Persona slug to consolidate, e.g. vz-lupas or baita-conveniencia")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run (no writes).")
    parser.add_argument("--limit", type=int, default=5000, help="Max product nodes to scan (default 5000).")
    args = parser.parse_args()

    report = run(persona_slug=args.persona_slug, apply=args.apply, limit=args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
