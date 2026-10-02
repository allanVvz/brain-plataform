from services import graph_agent_runtime_v3

stage = graph_agent_runtime_v3._lead_stage_for_turn
KNOWN = {"modelo_veiculo": [{"field_key": "modelo_veiculo", "status": "known", "value": "Ford Ka"}]}


def test_first_reply_without_facts_is_contacted():
    assert stage(confirmation_accepted=False, qualification_complete=False, grouped_facts={}) == "contatado"


def test_a_known_fact_means_engaged():
    assert stage(confirmation_accepted=False, qualification_complete=False, grouped_facts=KNOWN) == "engajado"


def test_unknown_or_pending_facts_are_not_engagement_yet():
    pending = {"servico": [{"status": "needs_confirmation"}]}
    assert stage(confirmation_accepted=False, qualification_complete=False, grouped_facts=pending) == "contatado"


def test_complete_qualification_is_qualified():
    assert stage(confirmation_accepted=False, qualification_complete=True, grouped_facts=KNOWN) == "qualificado"


def test_confirmed_summary_is_an_opportunity_for_the_closer():
    assert stage(confirmation_accepted=True, qualification_complete=True, grouped_facts=KNOWN) == "oportunidade"
