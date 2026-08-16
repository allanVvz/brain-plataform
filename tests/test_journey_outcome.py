from pathlib import Path

import pytest

from services import journey_outcome


OUTCOME_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
               "123_journey_outcome_events.sql").read_text(encoding="utf-8")


def journey(state, **metadata):
    return {"state": state, "lead_ref": 1, "metadata": dict(metadata)}


# ── derivacao ────────────────────────────────────────────────────────────────

def test_pre_qualification_has_no_outcome():
    for state in ("collecting", "awaiting_confirmation"):
        assert journey_outcome.derive(journey(state)) is None
    assert journey_outcome.derive(None) is None
    assert journey_outcome.derive({}) is None


@pytest.mark.parametrize("state", ["qualified_confirmed", "handed_off"])
def test_qualification_reads_as_qualificado(state):
    assert journey_outcome.derive(journey(state)) == journey_outcome.QUALIFICADO


def test_converted_separates_the_customer_yes_from_the_sale():
    """`converted` e o aceite; `sold` so aparece quando houve venda de fato.
    Os dois compartilham state='converted', entao o marcador e o que os
    distingue -- sem ele a lista mostraria 'vendido' para quem so disse sim."""
    assert journey_outcome.derive(journey("converted")) == journey_outcome.CONVERTIDO
    assert journey_outcome.derive(journey("converted", sold=True)) == journey_outcome.VENDIDO


@pytest.mark.parametrize("event", ["delivered", "service_completed"])
def test_completion_events_collapse_into_entregue(event):
    assert journey_outcome.derive(
        journey("closed", closing_event=event, sold=True)
    ) == journey_outcome.ENTREGUE


def test_cancellation_wins_over_a_previous_sale():
    assert journey_outcome.derive(
        journey("closed", closing_event="cancelled", sold=True)
    ) == journey_outcome.CANCELADO


def test_closed_without_a_closing_event_is_not_guessed():
    assert journey_outcome.derive(journey("closed", sold=True)) is None


# ── leitura em lote ──────────────────────────────────────────────────────────

def test_outcomes_for_leads_reads_once_for_the_whole_list(monkeypatch):
    calls = []

    def fake(persona_id, lead_refs, **_kwargs):
        calls.append((persona_id, list(lead_refs)))
        return [
            {"lead_ref": 1, "state": "handed_off", "metadata": {}},
            {"lead_ref": 2, "state": "converted", "metadata": {"sold": True}},
        ]

    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_current_journeys_by_lead_refs", fake,
    )
    outcomes = journey_outcome.outcomes_for_leads("persona:one", [2, 1, 1, None, 3])
    assert calls == [("persona:one", [1, 2, 3])]
    assert outcomes == {1: journey_outcome.QUALIFICADO, 2: journey_outcome.VENDIDO}


def test_outcomes_for_leads_skips_the_roundtrip_when_there_is_nothing_to_read(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("nao deve consultar sem leads")

    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_current_journeys_by_lead_refs", explode,
    )
    assert journey_outcome.outcomes_for_leads("persona:one", []) == {}
    assert journey_outcome.outcomes_for_leads("", [1, 2]) == {}


def test_decorate_leads_never_rewrites_the_manual_stage(monkeypatch):
    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_current_journeys_by_lead_refs",
        lambda *_a, **_k: [{"lead_ref": 7, "state": "converted", "metadata": {}}],
    )
    rows = [
        {"id": 7, "persona_id": "persona:one", "stage": "qualificado"},
        {"id": 8, "persona_id": "persona:one", "stage": "fechado"},
    ]
    decorated = journey_outcome.decorate_leads(rows)
    assert decorated[0]["journey_outcome"] == journey_outcome.CONVERTIDO
    assert decorated[0]["stage"] == "qualificado"
    assert decorated[1]["journey_outcome"] is None
    assert decorated[1]["stage"] == "fechado"


def test_decorate_leads_groups_by_persona_for_the_admin_listing(monkeypatch):
    seen = []

    def fake(persona_id, lead_refs, **_kwargs):
        seen.append(persona_id)
        return [{"lead_ref": ref, "state": "converted", "metadata": {"sold": True}}
                for ref in lead_refs]

    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_current_journeys_by_lead_refs", fake,
    )
    rows = [
        {"id": 1, "persona_id": "persona:a"},
        {"id": 2, "persona_id": "persona:b"},
    ]
    decorated = journey_outcome.decorate_leads(rows)
    assert sorted(seen) == ["persona:a", "persona:b"]
    assert [r["journey_outcome"] for r in decorated] == [
        journey_outcome.VENDIDO, journey_outcome.VENDIDO,
    ]


# ── contrato da migration 123 ────────────────────────────────────────────────

def test_migration_introduces_converted_without_creating_a_table():
    assert "CREATE TABLE" not in OUTCOME_SQL
    assert "'converted','sale_recorded','appointment_booked'" in OUTCOME_SQL
    assert "'sold',true" in OUTCOME_SQL


def test_proof_projection_never_regresses_a_settled_journey():
    """Desfecho comercial e registrado por humano. O proof do SDR continua
    escrevendo metadata, mas nao pode jogar uma jornada convertida ou fechada
    de volta para collecting/handed_off no proximo inbound."""
    projection = OUTCOME_SQL[
        OUTCOME_SQL.index("project_conversation_journey_from_proof_v1"):
        OUTCOME_SQL.index("record_conversation_journey_event_v1")
    ]
    assert "state IN ('converted','closed') INTO v_settled" in projection
    assert projection.count("CASE WHEN v_settled THEN state") == 4


def test_conversion_keeps_the_request_open_and_closing_events_close_it():
    events = OUTCOME_SQL[OUTCOME_SQL.index("record_conversation_journey_event_v1"):]
    assert "state=CASE WHEN state='closed' THEN state ELSE 'converted' END" in events
    assert events.count("'new_journey_created',false") >= 4
    assert "is_current=false,state='closed'" in events
