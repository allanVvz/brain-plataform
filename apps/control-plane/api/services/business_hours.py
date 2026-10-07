"""Business hours of one persona's agent: the single place that resolves them.

The published GraphBundle declares the default (`conversation_policy.business_hours`
on the persona node). The Agentes screen can save an agent-level setting in
`personas.config.business_hours`; any field it sets wins over the bundle, the rest
falls back to it. Everything downstream (transport, UI) reads the result of
`effective`, so a change saved on the screen applies end to end without
republishing the graph.
"""
from __future__ import annotations

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OVERRIDE_KEY = "business_hours"
_FIELDS = ("start", "end", "timezone")


class InvalidBusinessHours(ValueError):
    pass


def bundle_policy(publication: dict[str, Any] | None) -> dict[str, Any] | None:
    """`business_hours` of the active publication's persona node, or None."""
    graph = (publication or {}).get("document_json") or {}
    nodes = graph.get("nodes") if isinstance(graph, dict) else []
    persona_node = next((
        node for node in nodes or []
        if isinstance(node, dict)
        and str(node.get("node_type") or node.get("type") or "").lower() == "persona"
    ), {})
    node_data = persona_node.get("data") or persona_node.get("metadata") or {}
    policy = (node_data.get("conversation_policy") or {}).get("business_hours")
    return policy if isinstance(policy, dict) else None


def _override(persona: dict[str, Any] | None) -> dict[str, Any]:
    config = (persona or {}).get("config")
    value = config.get(OVERRIDE_KEY) if isinstance(config, dict) else None
    return value if isinstance(value, dict) else {}


def effective(persona: dict[str, Any] | None, publication: dict[str, Any] | None) -> dict[str, Any]:
    """Resolved hours: enabled flag, start/end/timezone and where they came from."""
    bundle = bundle_policy(publication)
    override = _override(persona)
    base = bundle or {}
    values = {field: override.get(field) or base.get(field) for field in _FIELDS}
    if "enabled" in override:
        enabled = bool(override["enabled"])
    else:
        enabled = bundle is not None and bundle.get("enabled") is not False
    # "Off" is a decision (switch off / graph says enabled=false); "none" means
    # nobody ever declared hours. Both leave replies unrestricted.
    switched_off = (not enabled) or bundle is None and "enabled" not in override
    complete = all(str(values[field] or "").strip() for field in _FIELDS)
    overridden = any(override.get(field) for field in (*_FIELDS, "enabled") if field in override)
    return {
        "enabled": bool(enabled and complete),
        "switched_off": bool(switched_off),
        "configured": complete,
        **{field: values[field] for field in _FIELDS},
        "source": "agent" if overridden else ("bundle" if bundle is not None else "none"),
    }


def validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Agentes-screen save: HH:MM times, IANA zone, start < end."""
    clean: dict[str, Any] = {}
    if patch.get("enabled") is not None:
        clean["enabled"] = bool(patch["enabled"])
    for field in ("start", "end"):
        if patch.get(field) is not None:
            try:
                parsed = time.fromisoformat(str(patch[field]).strip())
            except ValueError as exc:
                raise InvalidBusinessHours(f"{field} deve estar no formato HH:MM") from exc
            clean[field] = parsed.strftime("%H:%M")
    if patch.get("timezone") is not None:
        zone = str(patch["timezone"]).strip()
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise InvalidBusinessHours("fuso horario invalido") from exc
        clean["timezone"] = zone
    return clean


def merge_override(persona: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """New value for `config.business_hours` after applying a validated patch."""
    return {**_override(persona), **validate_patch(patch)}


def assert_ordered(values: dict[str, Any]) -> None:
    start, end = values.get("start"), values.get("end")
    if start and end and time.fromisoformat(str(start)) >= time.fromisoformat(str(end)):
        raise InvalidBusinessHours("o inicio deve ser antes do fim")
