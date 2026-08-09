from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import graph_agent_runtime_v3, lead_qualification


V3 = graph_agent_runtime_v3.RUNTIME_VERSION


def _v3_qualification(**overrides):
    base = {
        "version": V3,
        "complete": False,
        "resolved_fields": [],
        "missing_fields": [],
        "required_field_count": 0,
        "resolved_required_count": 0,
    }
    base.update(overrides)
    return base


# ── _v3_progress_score ───────────────────────────────────────────────────

def test_v3_progress_score_is_proportional_below_completion():
    qualification = _v3_qualification(required_field_count=4, resolved_required_count=2)
    assert lead_qualification._v3_progress_score(qualification) == 25


def test_v3_progress_score_is_exactly_50_at_completion():
    qualification = _v3_qualification(complete=True, required_field_count=7, resolved_required_count=7)
    assert lead_qualification._v3_progress_score(qualification) == 50


def test_v3_progress_score_never_exceeds_50_even_if_miscounted():
    # complete=True always wins regardless of what the counts say.
    qualification = _v3_qualification(complete=True, required_field_count=1, resolved_required_count=1)
    assert lead_qualification._v3_progress_score(qualification) == 50


def test_v3_progress_score_falls_back_to_field_key_counts_for_old_leads():
    # Leads persisted before required_field_count/resolved_required_count
    # existed only ever had resolved_fields/missing_fields.
    qualification = {
        "version": V3,
        "complete": False,
        "resolved_fields": ["nome_cliente"],
        "missing_fields": ["reclamacao_relato"],
    }
    assert lead_qualification._v3_progress_score(qualification) == 25


def test_v3_progress_score_is_zero_with_nothing_known():
    assert lead_qualification._v3_progress_score(_v3_qualification()) == 0


# ── score_for_display ────────────────────────────────────────────────────

def test_score_for_display_fechado_is_always_100():
    lead = {
        "stage": "fechado",
        "metadata": {"qualification": _v3_qualification(required_field_count=7, resolved_required_count=1)},
    }
    assert lead_qualification.score_for_display(lead) == 100


def test_score_for_display_oportunidade_is_always_75():
    lead = {"stage": "oportunidade", "metadata": {"qualification": _v3_qualification()}}
    assert lead_qualification.score_for_display(lead) == 75


def test_score_for_display_nao_qualificado_is_always_0():
    lead = {
        "stage": "nao_qualificado",
        "metadata": {"qualification": _v3_qualification(complete=True)},
    }
    assert lead_qualification.score_for_display(lead) == 0


def test_score_for_display_perdido_freezes_at_snapshot():
    lead = {
        "stage": "perdido",
        "metadata": {
            "qualification": _v3_qualification(
                required_field_count=4, resolved_required_count=1, score_at_perdido=30
            )
        },
    }
    # Even though live counts would compute a different value, the frozen
    # snapshot wins.
    assert lead_qualification.score_for_display(lead) == 30


def test_score_for_display_perdido_without_snapshot_falls_back_to_legacy_score():
    lead = {
        "stage": "perdido",
        "metadata": {"qualification": {"score": 42}},
    }
    assert lead_qualification.score_for_display(lead) == 42


def test_score_for_display_delegates_to_v3_formula_for_non_terminal_stage():
    lead = {
        "stage": "engajado",
        "metadata": {"qualification": _v3_qualification(required_field_count=4, resolved_required_count=2)},
    }
    assert lead_qualification.score_for_display(lead) == 25


def test_score_for_display_legacy_engine_unchanged():
    lead = {"stage": "qualificado", "metadata": {"qualification": {"version": "qualification_v1", "score": 67}}}
    assert lead_qualification.score_for_display(lead) == 67


# ── decorate_lead end-to-end ─────────────────────────────────────────────

def test_decorate_lead_qualification_score_uses_score_for_display():
    lead = {
        "lead_id": "123",
        "stage": "oportunidade",
        "metadata": {"qualification": _v3_qualification(required_field_count=7, resolved_required_count=3)},
    }
    decorated = lead_qualification.decorate_lead(lead)
    assert decorated["qualification_score"] == 75
