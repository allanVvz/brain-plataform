from pathlib import Path

import pytest

from services import journey_outcome


OUTCOME_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
               "123_journey_outcome_events.sql").read_text(encoding="utf-8")
REVERT_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
              "124_reversible_conversion.sql").read_text(encoding="utf-8")


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
            {"lead_ref": 1, "state": "handed_off", "sequence": 1, "is_current": True, "metadata": {}},
            {"lead_ref": 2, "state": "converted", "sequence": 1, "is_current": True,
             "converted_at": "2026-08-16T00:00:00Z", "metadata": {"sold": True}},
        ]

    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_journeys_by_lead_refs", fake,
    )
    outcomes = journey_outcome.outcomes_for_leads("persona:one", [2, 1, 1, None, 3])
    assert calls == [("persona:one", [1, 2, 3])]
    assert outcomes == {1: journey_outcome.QUALIFICADO, 2: journey_outcome.VENDIDO}


def test_outcomes_for_leads_skips_the_roundtrip_when_there_is_nothing_to_read(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("nao deve consultar sem leads")

    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_journeys_by_lead_refs", explode,
    )
    assert journey_outcome.outcomes_for_leads("persona:one", []) == {}
    assert journey_outcome.outcomes_for_leads("", [1, 2]) == {}


def test_decorate_leads_never_rewrites_the_manual_stage(monkeypatch):
    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_journeys_by_lead_refs",
        lambda *_a, **_k: [{"lead_ref": 7, "state": "converted", "sequence": 1,
                            "is_current": True, "metadata": {}}],
    )
    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_persona_configs_by_ids",
        lambda *_a, **_k: {"persona:one": {"portal": {"business_model": "appointment"}}},
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
    # o modelo de negocio viaja junto: a tela precisa dele para saber se o
    # pedido e comprado/entregue ou agendado/concluido
    assert decorated[0]["business_model"] == "appointment"


def test_decorate_leads_groups_by_persona_for_the_admin_listing(monkeypatch):
    seen = []

    def fake(persona_id, lead_refs, **_kwargs):
        seen.append(persona_id)
        return [{"lead_ref": ref, "state": "converted", "sequence": 1, "is_current": True,
                 "converted_at": "2026-08-16T00:00:00Z", "metadata": {"sold": True}}
                for ref in lead_refs]

    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_journeys_by_lead_refs", fake,
    )
    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_persona_configs_by_ids",
        lambda *_a, **_k: {},
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
    # persona sem config declarada cai em `sales`, nunca em None
    assert [r["business_model"] for r in decorated] == ["sales", "sales"]


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


# ── contrato da migration 124: conversao reversivel ──────────────────────────

def test_revert_returns_to_the_state_the_journey_actually_came_from():
    """Sem `state_before_conversion` o retorno seria um default adivinhado --
    uma jornada convertida a partir de `qualified_confirmed` voltaria para
    `handed_off` e pareceria ter sido entregue ao humano sem nunca ter sido."""
    assert "CREATE TABLE" not in REVERT_SQL
    assert "'state_before_conversion',v_previous" in REVERT_SQL
    assert "state=coalesce(nullif(metadata->>'state_before_conversion',''),'handed_off')" in REVERT_SQL
    assert "converted_at=NULL" in REVERT_SQL


def test_sale_makes_the_conversion_final():
    assert "conversion backed by a sale cannot be reverted" in REVERT_SQL
    revert = REVERT_SQL[REVERT_SQL.index("IF v_revert THEN"):]
    assert "(v_journey.metadata->>'sold')::boolean" in revert


def test_revert_frees_the_conversion_key_instead_of_appending_its_own():
    """O toggle precisa poder ir e voltar quantas vezes o operador corrigir.
    Se o revert apenas anexasse uma entrada, a chave de `converted` seguiria
    ocupada e a segunda conversao seria deduplicada em silencio."""
    start = REVERT_SQL.index("IF v_revert THEN")
    revert = REVERT_SQL[start:REVERT_SQL.index("IF v_sale THEN", start)]
    assert "e->>'type' IS DISTINCT FROM 'converted'" in revert
    # a varredura de idempotencia por metadata nao roda para o revert
    assert "ELSIF NOT v_revert THEN" in REVERT_SQL


def test_reverting_a_journey_that_is_not_converted_is_a_no_op():
    revert = REVERT_SQL[REVERT_SQL.index("IF v_revert THEN"):]
    assert "IF v_journey.state<>'converted' THEN" in revert
    assert revert.index("IF v_journey.state<>'converted' THEN") < revert.index("'deduplicated',true")


def test_revert_is_published_in_the_event_enum():
    assert "'converted','conversion_reverted','sale_recorded'" in REVERT_SQL


# ── contrato da migration 125: cancelar estorna a compra ─────────────────────

CANCEL_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
              "125_cancel_reverses_the_purchase.sql").read_text(encoding="utf-8")


def test_cancelling_reverses_the_purchase_in_the_ledger():
    """Antes da 125 a jornada fechava mas a linha em sales_conversions ficava
    `completed`: a tela dizia cancelado e a receita continuava contada."""
    assert "CREATE TABLE" not in CANCEL_SQL
    assert "status='cancelled'" in CANCEL_SQL
    assert "WHERE journey_id=v_journey.id AND status='completed'" in CANCEL_SQL
    assert "'reversed_conversions',v_reversed" in CANCEL_SQL


def test_cancelling_turns_the_sale_off_but_keeps_the_lead_converted():
    """Conversao e fato do lead, venda e fato do pedido. Depois do primeiro
    agendamento ou compra o lead esta convertido, e cancelar nao desfaz isso."""
    assert "(metadata-'sold'-'last_conversion')" in CANCEL_SQL
    fechamento = CANCEL_SQL[CANCEL_SQL.index("IF p_event_type='cancelled' THEN"):]
    assert "converted_at=NULL" not in fechamento


def test_a_cancelled_key_cannot_resurrect_the_sale():
    assert "idempotency key belongs to a cancelled conversion" in CANCEL_SQL


def test_first_conversion_ignores_cancelled_rows():
    """`lead_first_conversion` marca a primeira venda de verdade -- uma venda
    cancelada nao pode fazer a proxima parecer recorrencia."""
    assert "completed_at IS NOT NULL AND status<>'cancelled'" in CANCEL_SQL


# ── superficie do portal ──────────────────────────────────────────────────────

def test_portal_has_its_own_journey_event_route():
    """Conta `client` so passa pelo middleware em `/portal/*`, `/auth/*` e na
    midia de asset. A rota de `/agents` respondia 403 para o operador do portal
    antes mesmo de chegar ao backend -- 403 "Acesso negado." vem do middleware,
    nao da checagem de capability."""
    from middleware.auth import is_client_path_allowed
    from routes import portal

    assert is_client_path_allowed("POST", "/portal/leads/21/journey-events") is True
    assert is_client_path_allowed("POST", "/agents/leads/21/journey-events") is False

    rotas = {
        r.path for r in portal.router.routes
        if "POST" in getattr(r, "methods", set())
    }
    assert "/portal/leads/{lead_id}/journey-events" in rotas


def test_portal_route_scopes_the_lead_to_the_persona_in_the_url(monkeypatch):
    """A rota de `/agents` resolve a persona a partir da propria lead; a do
    portal exige que a lead pertenca a persona da URL, senao um operador com
    acesso a persona A registraria evento numa lead da persona B."""
    from fastapi import HTTPException
    from routes import portal

    monkeypatch.setattr(
        portal.supabase_client, "get_lead_by_ref",
        lambda _ref: {"id": 21, "persona_id": "persona:outra"},
    )
    with pytest.raises(HTTPException) as exc:
        portal._lead(21, "persona:da-url")
    assert exc.value.status_code == 404


# ── regras de negocio do ciclo do pedido ─────────────────────────────────────
#
# O ciclo completo: qualifica -> converte -> vende/agenda -> conclui/cancela ->
# proximo inbound abre o pedido seguinte. Cada teste abaixo fixa uma regra que
# ja quebrou pelo menos uma vez.

def jornada(seq, state, *, current=True, converted=False, **metadata):
    return {
        "lead_ref": 1, "sequence": seq, "state": state, "is_current": current,
        "converted_at": "2026-08-16T00:00:00Z" if converted else None,
        "metadata": dict(metadata),
    }


def test_pedido_fechado_continua_se_descrevendo_na_tela():
    """Ler so a jornada corrente fazia o pedido sumir no instante em que era
    concluido: `is_current` vira false e a tela ficava sem desfecho nenhum,
    com o botao de venda parecendo disponivel enquanto o backend respondia 409
    por nao haver jornada corrente."""
    fechada = [jornada(1, "closed", current=False, converted=True,
                       sold=True, closing_event="service_completed")]
    resumo = journey_outcome.summarize(fechada)
    assert resumo["journey_outcome"] == journey_outcome.ENTREGUE
    assert resumo["journey_is_open"] is False


def test_lead_fica_convertido_para_sempre_apos_a_primeira_venda():
    """Regra do negocio: depois do primeiro agendamento ou compra a lead esta
    convertida e nao volta para qualificada -- nem ao cancelar, nem no pedido
    seguinte."""
    cancelada = [jornada(1, "closed", current=False, converted=True,
                         closing_event="cancelled")]
    assert journey_outcome.summarize(cancelada)["lead_converted"] is True

    # pedido seguinte comeca do zero, a lead segue convertida
    segundo_ciclo = cancelada + [jornada(2, "handed_off")]
    resumo = journey_outcome.summarize(segundo_ciclo)
    assert resumo["lead_converted"] is True
    assert resumo["journey_outcome"] == journey_outcome.QUALIFICADO
    assert resumo["journey_is_open"] is True


def test_lead_sem_nenhuma_venda_nao_e_convertida():
    assert journey_outcome.summarize([jornada(1, "handed_off")])["lead_converted"] is False
    assert journey_outcome.summarize([])["lead_converted"] is False


def test_o_resumo_sempre_le_o_pedido_mais_recente():
    """Com varias jornadas, a tela fala do pedido atual -- nao do primeiro."""
    historico = [
        jornada(1, "closed", current=False, converted=True, sold=True,
                closing_event="delivered"),
        jornada(2, "closed", current=False, converted=True, closing_event="cancelled"),
        jornada(3, "converted", converted=True, sold=True),
    ]
    resumo = journey_outcome.summarize(list(reversed(historico)))  # ordem nao importa
    assert resumo["journey_outcome"] == journey_outcome.VENDIDO
    assert resumo["journey_sequence"] == 3
    assert resumo["journey_is_open"] is True


def test_sem_jornada_aberta_nao_ha_pedido_para_receber_evento():
    """O front usa isto para desabilitar os botoes: sem jornada corrente o
    backend levanta `current journey not found` e devolve 409. O ciclo so
    reinicia no proximo inbound do cliente."""
    fechada = journey_outcome.summarize(
        [jornada(1, "closed", current=False, closing_event="cancelled")]
    )
    assert fechada["journey_is_open"] is False
    sem_nada = journey_outcome.summarize([])
    assert sem_nada["journey_is_open"] is False and sem_nada["journey_outcome"] is None


def test_decoracao_expoe_os_dois_eixos_separados(monkeypatch):
    """`stage` (funil manual), `journey_outcome` (pedido) e `lead_converted`
    (permanente) sao tres fatos distintos e nenhum reescreve o outro."""
    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_journeys_by_lead_refs",
        lambda *_a, **_k: [jornada(1, "closed", current=False, converted=True,
                                   sold=True, closing_event="delivered")],
    )
    monkeypatch.setattr(
        journey_outcome.supabase_client, "get_persona_configs_by_ids",
        lambda *_a, **_k: {"p": {"portal": {"business_model": "appointment"}}},
    )
    row = journey_outcome.decorate_leads(
        [{"id": 1, "persona_id": "p", "stage": "qualificado"}]
    )[0]
    assert row["stage"] == "qualificado"
    assert row["journey_outcome"] == journey_outcome.ENTREGUE
    assert row["lead_converted"] is True
    assert row["journey_is_open"] is False
    assert row["business_model"] == "appointment"


# ── seletor de estado: contrato da migration 126 ─────────────────────────────

SELECTOR_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
                "126_journey_state_selector.sql").read_text(encoding="utf-8")


def test_selector_nao_cria_tabela_e_so_service_role_executa():
    assert "CREATE TABLE" not in SELECTOR_SQL
    assert "GRANT EXECUTE ON FUNCTION public.set_conversation_journey_state_v1" in SELECTOR_SQL
    assert "FROM PUBLIC,anon,authenticated" in SELECTOR_SQL


def test_reabrir_pedido_falha_se_ja_existe_um_mais_novo():
    """`idx_conversation_journeys_one_current` garante uma jornada corrente por
    lead. Reabrir por cima corromperia o indice, entao a guarda levanta erro
    nomeado em vez de deixar o banco recusar com violacao de indice."""
    assert "a newer order already exists for this lead" in SELECTOR_SQL
    guarda = SELECTOR_SQL[SELECTOR_SQL.index("IF v_open AND NOT v_journey.is_current"):]
    assert "sequence>v_journey.sequence" in guarda


def test_piso_permanente_impede_voltar_a_qualificado():
    assert "lead already converted: qualificado is no longer available" in SELECTOR_SQL
    assert "first_converted_at" in SELECTOR_SQL


def test_sair_de_vendido_estorna_a_conversao():
    assert "v_from='vendido' AND p_target IN ('qualificado','convertido')" in SELECTOR_SQL
    assert "status='cancelled'" in SELECTOR_SQL


def test_reentrar_em_vendido_usa_chave_nova():
    """Uma venda estornada queimou a chave; a proxima precisa de outra ou
    colidiria no UNIQUE(persona,source,idempotency_key)."""
    assert "'selector:'||v_journey.id::text||':'||v_seq::text" in SELECTOR_SQL


def test_carimbo_de_conversao_e_escrito_uma_vez_e_retroativo():
    """O carimbo tambem sai da via de eventos, para integracao e seletor
    concordarem, e o backfill cobre quem ja converteu antes da migration."""
    assert "trg_stamp_lead_first_conversion_v1" in SELECTOR_SQL
    assert "coalesce(metadata->>'first_converted_at'" in SELECTOR_SQL
    assert "UPDATE public.leads l SET" in SELECTOR_SQL  # backfill


def test_lead_converted_le_o_carimbo_e_nao_regride():
    """`converted_at` pode ser limpo pelo seletor; o carimbo nao."""
    assert journey_outcome.lead_converted(
        {"metadata": {"first_converted_at": "2026-08-16T00:00:00Z"}}
    ) is True
    assert journey_outcome.lead_converted({"metadata": {}}) is False
    assert journey_outcome.lead_converted(None) is False


# ── seletor de estado: religamento automatico da IA ──────────────────────────

def _corpo(target):
    from datetime import datetime, timezone
    from routes.agents import JourneyStateBody
    return JourneyStateBody(
        target=target, source="dashboard", occurred_at=datetime.now(timezone.utc),
    )


def test_fechar_o_pedido_religa_a_ia(monkeypatch):
    """Sem isto o lead segue mudo para sempre: o handoff grava
    `handoff_level='full'` e nenhum worker reclama `waiting_human`."""
    from routes import agents

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": True, "journey_closed": True})
    chamados = []
    monkeypatch.setattr(agents.agents_service, "resume_lead",
                        lambda ref: chamados.append(ref) or True)
    monkeypatch.setattr(agents.event_emitter, "emit", lambda *a, **k: None)

    resultado = agents.set_journey_state(21, _corpo("entregue"), "user:1")
    assert chamados == [21]
    assert resultado["ai_resumed"] is True


def test_estado_aberto_nao_religa_a_ia(monkeypatch):
    from routes import agents

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": True, "journey_closed": False})
    def explode(_ref):
        raise AssertionError("nao deve religar em estado aberto")
    monkeypatch.setattr(agents.agents_service, "resume_lead", explode)

    agents.set_journey_state(21, _corpo("vendido"), "user:1")


def test_qualificar_manualmente_pausa_a_ia(monkeypatch):
    """O SDR e a unica agente do lead: selecionar "qualificado" no rail deve
    pausar a IA do mesmo jeito que o SDR faz sozinho ao confirmar a
    qualificacao (conversation_runtime.commit -> handoff_level='full')."""
    from routes import agents

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": True, "journey_closed": False, "target": "qualificado"})
    chamados = []
    monkeypatch.setattr(agents.agents_service, "pause_lead",
                        lambda ref: chamados.append(ref) or True)
    monkeypatch.setattr(agents.event_emitter, "emit", lambda *a, **k: None)

    resultado = agents.set_journey_state(21, _corpo("qualificado"), "user:1")
    assert chamados == [21]
    assert resultado["ai_paused"] is True


def test_qualificar_repetido_nao_pausa_de_novo(monkeypatch):
    from routes import agents

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": False, "journey_closed": False, "target": "qualificado"})
    def explode(_ref):
        raise AssertionError("alvo repetido nao muda nada")
    monkeypatch.setattr(agents.agents_service, "pause_lead", explode)

    agents.set_journey_state(21, _corpo("qualificado"), "user:1")


def test_qualificar_manualmente_emite_evento_com_kwargs_validos(monkeypatch):
    """Regressao: event_emitter.emit(lead_ref=...) nao existe na assinatura
    real (entity_type/entity_id/persona_id/payload/level/source) e derrubava
    a resposta HTTP inteira com TypeError mesmo a mutacao de estado tendo
    sido aplicada (visto ao vivo em producao). Nao mockar emit() aqui -- o
    objetivo e exercitar a funcao de verdade e travar se o kwarg errado
    voltar; so a chamada a Postgres por baixo (insert_event) e mockada."""
    from routes import agents
    from services import supabase_client as real_supabase_client

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": True, "journey_closed": False, "target": "qualificado"})
    monkeypatch.setattr(agents.agents_service, "pause_lead", lambda ref: True)
    eventos = []
    monkeypatch.setattr(real_supabase_client, "insert_event",
                        lambda payload, **_kw: eventos.append(payload))

    resultado = agents.set_journey_state(21, _corpo("qualificado"), "user:1")

    assert resultado["ai_paused"] is True
    assert eventos and eventos[0]["event_type"] == "lead.ai_paused"
    assert eventos[0]["entity_id"] == "21"


def test_fechar_pedido_religa_ia_emite_evento_com_kwargs_validos(monkeypatch):
    from routes import agents
    from services import supabase_client as real_supabase_client

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": True, "journey_closed": True})
    monkeypatch.setattr(agents.agents_service, "resume_lead", lambda ref: True)
    eventos = []
    monkeypatch.setattr(real_supabase_client, "insert_event",
                        lambda payload, **_kw: eventos.append(payload))

    resultado = agents.set_journey_state(21, _corpo("entregue"), "user:1")

    assert resultado["ai_resumed"] is True
    assert eventos and eventos[0]["event_type"] == "lead.ai_resumed"
    assert eventos[0]["entity_id"] == "21"


def test_alvo_repetido_nao_religa_nem_grava(monkeypatch):
    from routes import agents

    monkeypatch.setattr(agents.supabase_client, "get_lead_by_ref",
                        lambda _ref: {"id": 21, "persona_id": "p"})
    monkeypatch.setattr(agents.supabase_client, "set_conversation_journey_state",
                        lambda **_kw: {"changed": False, "journey_closed": True})
    def explode(_ref):
        raise AssertionError("alvo repetido nao muda nada")
    monkeypatch.setattr(agents.agents_service, "resume_lead", explode)

    agents.set_journey_state(21, _corpo("entregue"), "user:1")


def test_recusas_da_rpc_viram_mensagem_legivel():
    from routes import agents
    assert "pedido mais novo" in agents._state_conflict_detail(
        Exception("a newer order already exists for this lead"))
    assert "ja converteu" in agents._state_conflict_detail(
        Exception("lead already converted: qualificado is no longer available"))
    assert agents._state_conflict_detail(Exception("boom")) == "Journey state could not be changed"


# ── segundo ciclo do SDR: o que atravessa o fim de um pedido ─────────────────

def test_contrato_marca_identidade_como_carry_over_e_pedido_nao():
    """Sem lista de nomes no codigo: o default vem da origem do field.

    Qualificacao da persona e o que o cliente E (nome), entao atravessa.
    `appointment_policy.required_fields` e o que ESTE pedido tem (data, janela)
    -- carregar "12/09" para o pedido seguinte seria errado.
    """
    from schemas.graph_json_v2 import GraphJson
    from services import graph_conversation_contract as contrato

    grafo = GraphJson.model_validate({
        "schema_version": "2.0", "graph_id": "g", "tenant": "t", "persona_slug": "p",
        "nodes": [
            {"id": "persona", "node_type": "persona", "slug": "p", "title": "P",
             "data": {
                 "qualification": {"fields": [{"key": "nome_cliente"}]},
                 "appointment_policy": {"required_fields": ["data"]},
             }},
            {"id": "ramo", "node_type": "product", "slug": "vitrificacao",
             "title": "Vitrificacao", "data": {
                 "qualification": {"fields": [{"key": "porte"}]},
             }},
        ],
        "edges": [{"id": "e1", "source": "persona", "target": "ramo",
                   "relation_type": "has_product", "primary_tree": True}],
    })
    campos = {
        f["key"]: f
        for f in contrato.compile_branch_contract(grafo, "ramo")["fields"]
    }
    assert campos["nome_cliente"]["carry_over"] is True
    assert campos["data"]["carry_over"] is False
    assert campos["porte"]["carry_over"] is False


def test_grafo_pode_sobrescrever_o_default_do_campo():
    from schemas.graph_json_v2 import GraphJson
    from services import graph_conversation_contract as contrato

    grafo = GraphJson.model_validate({
        "schema_version": "2.0", "graph_id": "g", "tenant": "t", "persona_slug": "p",
        "nodes": [{"id": "persona", "node_type": "persona", "slug": "p", "title": "P",
                   "data": {"qualification": {"fields": [
                       {"key": "nome_cliente"},
                       {"key": "humor_do_dia", "carry_over": False},
                   ]}}}],
        "edges": [],
    })
    campos = {f["key"]: f for f in contrato.compile_branch_contract(grafo, None)["fields"]}
    assert campos["nome_cliente"]["carry_over"] is True
    assert campos["humor_do_dia"]["carry_over"] is False


def _documento(carry, nao_carry):
    return {"branch_contracts": {"ramo": {"fields": [
        {"key": carry, "carry_over": True},
        {"key": nao_carry, "carry_over": False},
    ]}}}


def test_ciclo_novo_herda_identidade_e_esquece_o_servico(monkeypatch):
    from services import graph_agent_runtime_v3 as runtime

    monkeypatch.setattr(runtime.supabase_client, "get_journey_ledger_facts",
                        lambda _jid: [
                            {"field_key": "nome_cliente", "status": "known",
                             "value_json": "Ana", "id": "f1"},
                            {"field_key": "servico", "status": "known",
                             "value_json": "vitrificacao", "id": "f2"},
                        ])
    ledger = runtime._seed_carried_facts(
        {"facts": {}, "facts_by_key": {}},
        _documento("nome_cliente", "servico"),
        {"id": "jornada-1"},
    )
    assert ledger["facts"]["nome_cliente"]["value"] == "Ana"
    assert ledger["facts"]["nome_cliente"]["carried_from_journey"] == "jornada-1"
    assert "servico" not in ledger["facts"]


def test_fato_herdado_nunca_sobrescreve_o_do_ciclo_atual(monkeypatch):
    """Se o cliente ja corrigiu o nome neste pedido, o valor novo vence."""
    from services import graph_agent_runtime_v3 as runtime

    monkeypatch.setattr(runtime.supabase_client, "get_journey_ledger_facts",
                        lambda _jid: [{"field_key": "nome_cliente", "status": "known",
                                       "value_json": "Ana", "id": "f1"}])
    atual = {"facts": {"nome_cliente": {"value": "Ana Paula"}},
             "facts_by_key": {"nome_cliente": [{"value": "Ana Paula"}]}}
    ledger = runtime._seed_carried_facts(
        atual, _documento("nome_cliente", "servico"), {"id": "jornada-1"},
    )
    # Ledger com fato proprio nao e semeado de forma alguma.
    assert ledger["facts"]["nome_cliente"]["value"] == "Ana Paula"


def test_fato_incerto_nao_atravessa(monkeypatch):
    """`unknown` (o `ignored_twice`) nao vira verdade no ciclo seguinte."""
    from services import graph_agent_runtime_v3 as runtime

    monkeypatch.setattr(runtime.supabase_client, "get_journey_ledger_facts",
                        lambda _jid: [{"field_key": "nome_cliente", "status": "unknown",
                                       "value_json": None, "id": "f1"}])
    ledger = runtime._seed_carried_facts(
        {"facts": {}, "facts_by_key": {}},
        _documento("nome_cliente", "servico"), {"id": "jornada-1"},
    )
    assert ledger["facts"] == {}


def test_falha_ao_herdar_nao_derruba_o_turno(monkeypatch):
    from services import graph_agent_runtime_v3 as runtime

    def explode(_jid):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(runtime.supabase_client, "get_journey_ledger_facts", explode)
    ledger = runtime._seed_carried_facts(
        {"facts": {}, "facts_by_key": {}},
        _documento("nome_cliente", "servico"), {"id": "jornada-1"},
    )
    assert ledger["facts"] == {}
