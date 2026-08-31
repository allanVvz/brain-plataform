from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_monorepo_boundary_guard_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_monorepo_boundaries.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_template_has_one_owner() -> None:
    templates = list((ROOT / "apps").rglob("persona-conversation-template.json"))
    assert templates == [ROOT / "apps/conversation-runtime/n8n/persona-conversation-template.json"]


def test_deployable_apps_do_not_require_deep_repository_parents_at_import_time() -> None:
    for app in ("control-plane", "conversation-runtime"):
        source = (
            ROOT / "apps" / app / "api" / "services" / "deepseek_n8n_service.py"
        ).read_text(encoding="utf-8")
        assert "parents[4]" not in source


def test_v2_event_is_normalized_to_v3() -> None:
    sys.path[:0] = [str(ROOT / "packages/brain-contracts")]
    from brain_contracts.compat import parse_conversation_event

    event = parse_conversation_event({
        "contract_version": "2", "inbound_id": "inbound-1", "correlation_id": "correlation-1",
        "persona_id": "persona-1", "persona_slug": "fixture", "lead_ref": "lead-1",
        "channel_binding_id": "binding-1", "provider": "internal_validator",
        "received_at": "2026-08-31T12:00:00Z", "message_type": "text", "content": {"text": "oi"},
    })
    assert event.contract_version == "3"
    assert event.canonical_inbound_id == "inbound-1"


def test_service_ownership_describes_all_deployable_apps() -> None:
    payload = json.loads((ROOT / "apps/service-boundaries.json").read_text(encoding="utf-8"))
    assert set(payload["apps"]) == {"gateway", "control-plane", "conversation-runtime", "transport"}
