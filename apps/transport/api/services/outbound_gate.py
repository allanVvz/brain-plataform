"""One rule for every queued outbound: it goes out only while its sender may speak.

Every message the queue sends, from any provider (Meta Cloud, Evolution) and any
source (agent reply, campaign, proactive notice, a person in the portal or the
Chatwoot app), passes the same gate at send time:

* the channel (binding) is paused   -> the message is held, nothing is lost;
* the lead is paused (human took over) and the message is the agent's ->
  held, or superseded if a person already answered after it was written;
* otherwise it is sent, at the channel's own pace (see `SendRate`).

A held message shows as "Pausada" in the queue and is released automatically
when its reason clears; the dispatcher meanwhile moves on to the next lead.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

HOLD_LEAD_PAUSED = "lead_paused"
HOLD_CHANNEL_PAUSED = "channel_paused"
HOLD_REASONS = (HOLD_LEAD_PAUSED, HOLD_CHANNEL_PAUSED)

# Meta Cloud allows far more; Evolution (a linked phone) gets banned when it
# behaves like a bot blasting messages, so it is paced like a person.
DEFAULT_RATE_PER_SECOND = {"meta_cloud": 20.0, "evolution_baileys": 1.0}
FALLBACK_RATE_PER_SECOND = 5.0


def is_human(row: dict[str, Any]) -> bool:
    return str((row.get("payload") or {}).get("sender_type") or "") == "human"


def lead_paused(lead: dict[str, Any] | None) -> bool:
    lead = lead or {}
    return bool(lead.get("ai_paused")) or str(lead.get("handoff_level") or "none") != "none"


def channel_paused(binding: dict[str, Any] | None) -> bool:
    binding = binding or {}
    metadata = binding.get("metadata") or {}
    return bool(metadata.get("safety_paused")) or binding.get("connection_status") == "safety_paused"


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def person_answered_after(messages: list[dict[str, Any]], created_at: Any) -> bool:
    """True if a person sent this lead a message after `created_at`."""
    written = _parse(created_at)
    if written is None:
        return False
    for message in messages:
        if message.get("direction") != "outbound":
            continue
        sender = str((message.get("metadata") or {}).get("sender_type") or message.get("role") or "")
        sent = _parse(message.get("created_at"))
        if sender == "human" and sent is not None and sent > written:
            return True
    return False


def decide(
    row: dict[str, Any], *, binding: dict[str, Any] | None, lead: dict[str, Any] | None,
    messages: list[dict[str, Any]] | None = None,
) -> tuple[str, str | None]:
    """("send", None) | ("hold", reason) | ("supersede", reason)."""
    if channel_paused(binding):
        return "hold", HOLD_CHANNEL_PAUSED
    if not is_human(row) and lead_paused(lead):
        if person_answered_after(messages or [], row.get("created_at")):
            return "supersede", "person_answered"
        return "hold", HOLD_LEAD_PAUSED
    return "send", None


def hold_cleared(reason: str, *, binding: dict[str, Any] | None, lead: dict[str, Any] | None) -> bool:
    if reason == HOLD_CHANNEL_PAUSED:
        return not channel_paused(binding)
    if reason == HOLD_LEAD_PAUSED:
        return not lead_paused(lead) and not channel_paused(binding)
    return False


def rate_for(binding: dict[str, Any] | None) -> float:
    binding = binding or {}
    try:
        configured = float((binding.get("metadata") or {}).get("send_rate_per_second") or 0)
    except (TypeError, ValueError):
        configured = 0.0
    if configured > 0:
        return configured
    return DEFAULT_RATE_PER_SECOND.get(str(binding.get("provider") or ""), FALLBACK_RATE_PER_SECOND)


class SendRate:
    """Per-channel pacing shared by the dispatcher threads (one slot per binding)."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep) -> None:
        self._clock, self._sleep = clock, sleep
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, binding: dict[str, Any] | None) -> float:
        """Block until this binding may send again; returns the seconds waited."""
        key = str((binding or {}).get("id") or "")
        interval = 1.0 / rate_for(binding)
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot.get(key, now))
            self._next_slot[key] = slot + interval
        delay = slot - now
        if delay > 0:
            self._sleep(delay)
        return delay
