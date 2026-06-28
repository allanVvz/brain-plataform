"""Sofia FAQ tool — adaptar_faqs_universais_ao_grafo (pure logic, no Supabase)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _branch():
    nodes = [
        {"id": "b1", "node_type": "brand", "title": "VZ Lupas", "slug": "vz-lupas"},
        {"id": "g1", "node_type": "product_group", "title": "Juliet", "slug": "grupo-juliet"},
        {"id": "p1", "node_type": "product", "title": "Juliet Carbon Black Iridium", "slug": "juliet-carbon-black"},
        {"id": "f1", "node_type": "faq", "title": "Como comprar Juliet?", "slug": "faq-juliet"},
    ]
    edges = [
        {"source_node_id": "b1", "target_node_id": "g1", "metadata": {"active": True}},
        {"source_node_id": "g1", "target_node_id": "p1", "metadata": {"active": True}},
        {"source_node_id": "p1", "target_node_id": "f1", "metadata": {"active": True}},
    ]
    return nodes, edges


# ── intent detection ─────────────────────────────────────────────────────────

def test_detect_faq_intents():
    from services import sofia_faq_tool as t

    assert t.detect_faq_generation_intent("gere novamente as perguntas desse node")["intent"] == "gerar_novamente_faqs_do_node"
    assert t.detect_faq_generation_intent("gere novo FAQ com o grafo")["intent"] == "gerar_faqs_para_node"
    assert t.detect_faq_generation_intent("quero criar 10 perguntas por FAQ")["count"] == 10
    assert t.detect_faq_generation_intent("gere 5 perguntas para esse produto")["count"] == 5
    upd = t.detect_faq_generation_intent("quero atualizar Como comprar Óculos Juliet?")
    # 'atualizar' alone without faq/pergunta is not a FAQ-gen intent
    assert upd is None
    assert t.detect_faq_generation_intent("melhore essa pergunta")["intent"] == "atualizar_faq"
    assert t.detect_faq_generation_intent("conecte a brand na persona") is None


def test_clamp_count():
    from services import sofia_faq_tool as t

    assert t.clamp_count(None) == t.DEFAULT_FAQ_COUNT
    assert t.clamp_count(0) == 1
    assert t.clamp_count(999) == t.MAX_FAQ_COUNT
    assert t.clamp_count("3") == 3


# ── parent selection ─────────────────────────────────────────────────────────

def test_faq_target_climbs_to_product_parent():
    from services import sofia_faq_tool as t

    nodes, edges = _branch()
    faq = next(n for n in nodes if n["id"] == "f1")
    parent = t.select_faq_parent(faq, nodes, edges)
    assert parent["id"] == "p1"  # prefers the Product anchor


def test_product_target_anchors_on_itself():
    from services import sofia_faq_tool as t

    nodes, edges = _branch()
    product = next(n for n in nodes if n["id"] == "p1")
    assert t.select_faq_parent(product, nodes, edges)["id"] == "p1"


def test_product_group_used_when_no_product():
    from services import sofia_faq_tool as t

    # group branch without a product node below it
    nodes = [
        {"id": "b1", "node_type": "brand", "title": "VZ Lupas"},
        {"id": "g1", "node_type": "product_group", "title": "Radar"},
    ]
    edges = [{"source_node_id": "b1", "target_node_id": "g1", "metadata": {"active": True}}]
    group = nodes[1]
    out = t.adaptar_faqs_universais_ao_grafo(target_node=group, nodes=nodes, edges=edges, count=3)
    assert out["parent_node_type"] == "product_group"
    assert "Radar" in out["suggestions"][0]["question"]


# ── generation ───────────────────────────────────────────────────────────────

def test_generates_n_adapted_suggestions():
    from services import sofia_faq_tool as t

    nodes, edges = _branch()
    product = next(n for n in nodes if n["id"] == "p1")
    out = t.adaptar_faqs_universais_ao_grafo(target_node=product, nodes=nodes, edges=edges, count=10, persona_slug="allanvvz")

    assert out["count"] == 10
    assert len(out["suggestions"]) == 10
    assert out["parent_node_id"] == "p1"
    assert out["source_tool"] == t.SOURCE_TOOL
    # adapted, not generic: the real product + brand appear in the copy
    first = out["suggestions"][0]
    assert "Juliet Carbon Black Iridium" in first["question"]
    assert "VZ Lupas" in first["answer"]
    assert out["source_context"]["brand"] == "VZ Lupas"
    assert out["source_context"]["generated_from_node_id"] == "p1"


def test_regenerate_uses_same_count_reproducibly():
    from services import sofia_faq_tool as t

    nodes, edges = _branch()
    product = next(n for n in nodes if n["id"] == "p1")
    a = t.adaptar_faqs_universais_ao_grafo(target_node=product, nodes=nodes, edges=edges, count=4)
    b = t.adaptar_faqs_universais_ao_grafo(target_node=product, nodes=nodes, edges=edges, count=4)
    assert [s["question"] for s in a["suggestions"]] == [s["question"] for s in b["suggestions"]]
    assert len(a["suggestions"]) == 4


# ── node-type classification (Audience is not a Product) ─────────────────────

_FORBIDDEN = ["comprar o", "acompanha caixa", "acompanha case", "flanela", "prazo de envio", "prazo de entrega", "garantia do", "parcelar", "frete"]


def _allan_audience():
    """Brand Allan Rodrigues -> Audience Técnicos, with NO product in the branch."""
    nodes = [
        {"id": "b1", "node_type": "brand", "title": "Allan Rodrigues"},
        {"id": "a1", "node_type": "audience", "title": "Técnicos",
         "metadata": {"markdown": "Pessoas técnicas de 25 a 40 anos. gostam de tecnologia"}},
    ]
    edges = [{"source_node_id": "b1", "target_node_id": "a1", "metadata": {"active": True}}]
    return nodes, edges


def test_audience_does_not_generate_purchase_questions():
    from services import sofia_faq_tool as t

    nodes, edges = _allan_audience()
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[1], nodes=nodes, edges=edges, count=6)

    assert out["category"] == "audience"
    assert out["commercial_object_name"] is None
    joined = " ".join(s["question"].lower() + " " + s["answer"].lower() for s in out["suggestions"])
    for bad in _FORBIDDEN:
        assert bad not in joined, f"forbidden commercial wording leaked: {bad}"
    assert "comprar o técnicos" not in joined


def test_audience_generates_qualification_questions_from_markdown():
    from services import sofia_faq_tool as t

    nodes, edges = _allan_audience()
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[1], nodes=nodes, edges=edges, count=6)
    questions = " ".join(s["question"].lower() for s in out["suggestions"])

    # qualification / discovery vocabulary, and the audience markdown descriptor
    assert "público" in questions or "publico" in questions
    descriptor_hit = any("pessoas técnicas de 25 a 40 anos" in s["question"].lower() for s in out["suggestions"])
    assert descriptor_hit


def test_brand_without_product_has_no_shipping_wording():
    from services import sofia_faq_tool as t

    nodes = [{"id": "b1", "node_type": "brand", "title": "Allan Rodrigues"}]
    edges = []
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[0], nodes=nodes, edges=edges, count=5)
    assert out["category"] == "brand"
    joined = " ".join(s["question"].lower() + " " + s["answer"].lower() for s in out["suggestions"])
    for bad in _FORBIDDEN:
        assert bad not in joined


def test_product_still_generates_purchase_questions():
    from services import sofia_faq_tool as t

    nodes, edges = _branch()
    product = next(n for n in nodes if n["id"] == "p1")
    out = t.adaptar_faqs_universais_ao_grafo(target_node=product, nodes=nodes, edges=edges, count=4)
    assert out["category"] == "product"
    assert out["commercial_object_type"] == "product"
    assert any("comprar" in s["question"].lower() for s in out["suggestions"])


def test_copy_generates_spec_questions():
    from services import sofia_faq_tool as t

    nodes = [
        {"id": "p1", "node_type": "product", "title": "Notebook X"},
        {"id": "c1", "node_type": "copy", "title": "Copy Notebook",
         "metadata": {"markdown": "Processador i5 e 2TB de armazenamento para quem precisa de espaço."}},
    ]
    edges = [{"source_node_id": "p1", "target_node_id": "c1", "metadata": {"active": True}}]
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[1], nodes=nodes, edges=edges, count=5)
    assert out["category"] == "copy"
    joined = " ".join(s["question"] for s in out["suggestions"])
    assert "i5" in joined
    assert "2TB" in joined


def test_faq_under_copy_uses_whole_product_branch_not_copy_templates():
    from services import sofia_faq_tool as t

    nodes = [
        {"id": "b1", "node_type": "brand", "title": "Tock Fatal", "metadata": {"markdown": "Marca Tock Fatal."}},
        {"id": "bf1", "node_type": "briefing", "title": "Briefing inverno", "metadata": {"markdown": "Briefing para produtos quentes e baratos."}},
        {"id": "c1", "node_type": "campaign", "title": "Campanha inverno", "metadata": {"markdown": "Campanha de inverno para giro rapido."}},
        {"id": "a1", "node_type": "audience", "title": "Atacarejo inverno", "metadata": {"markdown": "Publico que compra para revenda e busca preco acessivel."}},
        {"id": "g1", "node_type": "product_group", "title": "Modal", "metadata": {"markdown": "Grupo de produtos Modal."}},
        {"id": "p1", "node_type": "product", "title": "Kit Modal 1", "metadata": {"markdown": "Kit Modal 1 com opcoes para revenda."}},
        {"id": "cp1", "node_type": "copy", "title": "Copy Kit Modal 1", "metadata": {"markdown": "Copy de divulgacao para Kit Modal 1."}},
        {"id": "f1", "node_type": "faq", "title": "FAQ Kit Modal 1"},
    ]
    edges = [
        {"source_node_id": "b1", "target_node_id": "bf1", "metadata": {"active": True}},
        {"source_node_id": "bf1", "target_node_id": "c1", "metadata": {"active": True}},
        {"source_node_id": "c1", "target_node_id": "a1", "metadata": {"active": True}},
        {"source_node_id": "a1", "target_node_id": "g1", "metadata": {"active": True}},
        {"source_node_id": "g1", "target_node_id": "p1", "metadata": {"active": True}},
        {"source_node_id": "p1", "target_node_id": "cp1", "metadata": {"active": True}},
        {"source_node_id": "cp1", "target_node_id": "f1", "metadata": {"active": True}},
    ]

    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[-1], nodes=nodes, edges=edges, count=5)
    joined = " ".join(s["question"] + " " + s["answer"] for s in out["suggestions"]).lower()

    assert out["parent_node_type"] == "copy"
    assert out["category"] == "product"
    assert out["commercial_object_name"] == "Kit Modal 1"
    assert "principal promessa desta copy" not in joined
    assert "argumento esta copy" not in joined
    assert "detalhe do galho" not in joined
    assert "copy de divulgacao" not in joined
    assert "kit modal 1" in joined
    assert "tock fatal" in joined
    assert "atacarejo inverno" in joined


def test_briefing_about_courses_asks_about_courses():
    from services import sofia_faq_tool as t

    nodes = [
        {"id": "br1", "node_type": "brand", "title": "Allan Rodrigues"},
        {"id": "bf1", "node_type": "briefing", "title": "Briefing Cursos",
         "metadata": {"markdown": "Cursos de eletrônica e automação para iniciantes."}},
    ]
    edges = [{"source_node_id": "br1", "target_node_id": "bf1", "metadata": {"active": True}}]
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[1], nodes=nodes, edges=edges, count=5)
    assert out["category"] == "briefing"
    joined = " ".join(s["question"].lower() + " " + s["answer"].lower() for s in out["suggestions"])
    assert "briefing" in joined
    for bad in _FORBIDDEN:
        assert bad not in joined


def test_allan_branch_does_not_inherit_vz_lupas_language():
    from services import sofia_faq_tool as t

    nodes, edges = _allan_audience()
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[1], nodes=nodes, edges=edges, count=6)
    joined = " ".join(s["question"].lower() + " " + s["answer"].lower() for s in out["suggestions"])
    assert "vz lupas" not in joined
    assert "óculos" not in joined and "oculos" not in joined


def test_audience_with_product_below_relates_audience_to_object():
    from services import sofia_faq_tool as t

    nodes = [
        {"id": "b1", "node_type": "brand", "title": "Allan Rodrigues"},
        {"id": "a1", "node_type": "audience", "title": "Técnicos", "metadata": {"markdown": "Pessoas técnicas."}},
        {"id": "p1", "node_type": "product", "title": "Kit Arduino"},
    ]
    edges = [
        {"source_node_id": "b1", "target_node_id": "a1", "metadata": {"active": True}},
        {"source_node_id": "a1", "target_node_id": "p1", "metadata": {"active": True}},
    ]
    out = t.adaptar_faqs_universais_ao_grafo(target_node=nodes[1], nodes=nodes, edges=edges, count=5)
    assert out["category"] == "audience_object"
    assert out["commercial_object_name"] == "Kit Arduino"
    joined = " ".join(s["question"] for s in out["suggestions"])
    # relates the audience to the object, never "buy the audience"
    assert "Kit Arduino" in joined
    assert "Técnicos" in joined
    assert "comprar o Técnicos" not in joined.lower()
