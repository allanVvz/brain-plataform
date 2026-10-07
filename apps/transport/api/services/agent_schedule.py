"""Business hours as the agent's on/off switch.

Outside the persona's hours the agent is off for every lead, with one exception:
a dialogue that is still going keeps its agent until it pauses. "Going" means the
lead was answered (by the agent or by a person) less than ``DIALOGUE_GRACE`` ago;
once the conversation is idle past that, a new customer message finds the agent
off and waits for the next opening instead of being answered at night.

The window itself (default from the GraphBundle, adjustable on the Agentes screen)
is resolved by the control plane; this module only applies it. Hours are never
used to hold a reply that is already being written, nor a person's message.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

from services import control_plane_client
from services.whatsapp_outbox import _published_schedule

DIALOGUE_GRACE = timedelta(minutes=10)
_POLICY_TTL_SECONDS = 60.0
_policy_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def hours_for(persona_id: str) -> dict[str, Any] | None:
    """Effective business hours (None = unrestricted), cached for a minute."""
    cached = _policy_cache.get(persona_id)
    if cached and _time.monotonic() - cached[0] < _POLICY_TTL_SECONDS:
        return cached[1]
    hours = control_plane_client.published_outbound_policy(persona_id).get("published_business_hours")
    _policy_cache[persona_id] = (_time.monotonic(), hours)
    return hours


def opening_after(hours: dict[str, Any] | None, now: datetime) -> datetime | None:
    """The next opening if the window is closed at `now`, else None."""
    if not hours:
        return None
    schedule = _published_schedule({"published_business_hours": hours}, now=now)
    if not schedule or not schedule["closed"]:
        return None
    return parse_time(schedule["available_at"])


def dialogue_active(messages: list[dict[str, Any]], *, at: datetime) -> bool:
    """True if someone answered this lead within the grace period before `at`."""
    for message in messages:
        if message.get("direction") != "outbound" or message.get("status") in {"failed", "dead_letter"}:
            continue
        sent = parse_time(message.get("created_at"))
        if sent is not None and timedelta(0) <= at - sent <= DIALOGUE_GRACE:
            return True
    return False


def deferral(
    persona_id: str, *, messages: list[dict[str, Any]], inbound_at: datetime,
    now: datetime | None = None,
) -> datetime | None:
    """When the agent may take this inbound, or None if it can answer now.

    A failed policy lookup never silences the agent: technical failures are
    logged by the caller and the conversation proceeds.
    """
    now = now or datetime.now(timezone.utc)
    try:
        opening = opening_after(hours_for(persona_id), now)
    except Exception:
        return None
    if opening is None or dialogue_active(messages, at=inbound_at):
        return None
    return opening
