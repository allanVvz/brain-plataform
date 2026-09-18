from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "services" / "agents_service.py").read_text(encoding="utf-8")


def test_legacy_reactivation_copy_cannot_bypass_the_proactive_proof_queue():
    section = SOURCE.split("def reactivation_notice", 1)[1].split("def _session_window_closed", 1)[0]
    assert "published_proactive_proof_required" in section
    assert "enqueue_outbound(" not in section
    assert "enqueue_proactive_with_proof_v1" in section
