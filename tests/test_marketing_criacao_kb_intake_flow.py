#!/usr/bin/env python3
"""[PATH: CREATE] /marketing/criacao -> kb-intake full-tree materialization.

The /marketing/criacao screen embeds the CaptureWorkspace, which drives the
Sofia Create path over /kb-intake/start + /kb-intake/message. The operator:

  1. configures a session (persona vz-lupas, source https://vzlupas.com),
  2. sends "extraia os produtos do site 9 produtos 3 grupos de produtos ...",
  3. confirms "sim crie toda a arvore inspirada na vz lupas ...".

Bug (pre-fix): the LLM frequently stalled ("vou comecar pelo briefing"), asked
clarifying questions, or emitted a plan with broken parent links, so the tree
never materialized. The deterministic full-tree builder fixes this: on an
explicit "crie toda a arvore" confirmation, when the LLM produced no usable
plan, the backend builds the canonical chain from the crawler candidates.

This test mocks the LLM (so it produces NO plan, the worst case) and the
crawler (real-shaped candidates) and asserts the full tree is materialized and
validates clean. No network, no live backend, no LLM key required.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc  # noqa: E402


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


# --- Fixtures: a crawler capture shaped like the real vzlupas.com output ---- #
_CANDIDATES = [
    {"title": "Óculos Radar Areia Ruby - Ev Path Matte Sand Torch", "prices": ["227.30"], "source": "https://vzlupas.com/p/radar-areia"},
    {"title": "Óculos Radar Transparente - Ev Path Lilac Low Light", "prices": ["193.30"], "source": "https://vzlupas.com/p/radar-transp"},
    {"title": "Óculos Radar Ev Path Copper Prizm Tungsten", "prices": ["219.00"], "source": "https://vzlupas.com/p/radar-copper"},
    {"title": "Óculos Juliet Roxa - Plasma Violet (Polarizado)", "prices": ["197.30"], "source": "https://vzlupas.com/p/juliet-roxa"},
    {"title": "Óculos Juliet Plasma Gold Custom", "prices": ["212.30"], "source": "https://vzlupas.com/p/juliet-gold"},
    {"title": "Óculos Juliet Squared Black", "prices": ["197.60"], "source": "https://vzlupas.com/p/juliet-squared"},
    {"title": "Óculos HSTN Preto - Matte Black Prizm Black", "prices": ["226.00"], "source": "https://vzlupas.com/p/hstn-preto"},
    {"title": "Óculos HSTN Marrom - Brown Tungsten", "prices": [], "source": "https://vzlupas.com/p/hstn-marrom"},
    {"title": "Óculos HSTN Clear", "prices": ["198.00"], "source": "https://vzlupas.com/p/hstn-clear"},
]

_TOCK_FATAL_CANDIDATES = [
    {
        "title": "Kit Modal 2 - Urso Estampado",
        "prices": ["249.00", "459.00", "59.90"],
        "handle": "kit-modal-2-urso-estampado",
        "image_url": "https://tockfatal.com/cdn/shop/files/6.jpg?v=1774866754&width=500",
        "source": "shopify_json",
    },
    {
        "title": "Kit Modal 1 (9 cores disponíveis)",
        "prices": ["249.00", "459.00", "59.90"],
        "handle": "kit-modal-1-1-peca-9-cores-disponiveis",
        "image_url": "https://tockfatal.com/cdn/shop/files/1.png?v=1774854265&width=500",
        "source": "shopify_json",
    },
]


def _fake_capture(url: str) -> dict:
    return {
        "url": url,
        "final_url": url,
        "status_code": 200,
        "confidence": 0.85,
        "confidence_label": "alta",
        "product_candidates": list(_CANDIDATES),
        "warnings": [],
        "raw_text_preview": "catalogo vz lupas",
        "stages": [],
    }


def _fake_tock_capture(url: str) -> dict:
    return {
        "url": url,
        "final_url": url,
        "status_code": 200,
        "confidence": 0.85,
        "confidence_label": "alta",
        "product_candidates": list(_TOCK_FATAL_CANDIDATES),
        "warnings": ["Certificado SSL nao validou localmente; captura refeita sem verificacao de certificado."],
        "raw_text_preview": "Coleção Modais de Inverno Kit Modal 2 - Urso Estampado R$ 59,90 Kit Modal 1 (9 cores disponíveis) R$ 59,90",
        "stages": [],
    }


class _FakeRouter:
    """Stands in for ModelRouter. Produces NO <knowledge_plan> — only a
    conversational clarifying answer — to prove the deterministic builder is
    what materializes the tree (worst case for the LLM)."""

    def messages_create(self, *args, **kwargs):
        return (
            "Claro! Para montar a arvore preciso confirmar alguns detalhes: "
            "qual o nome da campanha e o publico-alvo?"
        )


@contextmanager
def _mocked_backends():
    prev_router = svc.ModelRouter
    prev_crawl = svc.crawl_catalog_url
    svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
    svc.crawl_catalog_url = _fake_capture  # type: ignore[assignment]
    # Canonical mode — matches the docker compose default (SOFIA_TOOLS_ENABLED
    # defaults to true). In this mode normalize is a pure cleanup pass and the
    # per-product copy/faq the builder emits are preserved (9 each).
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        yield
    finally:
        svc.ModelRouter = prev_router  # type: ignore[assignment]
        svc.crawl_catalog_url = prev_crawl  # type: ignore[assignment]
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools


def _run_flow() -> dict:
    started = svc.start_bootstrap_session(
        "gpt-4o-mini",
        initial_context="Missao: vz-lupas | Fonte: https://vzlupas.com | Blocos: briefing, audience, product, copy, faq, campaign, brand",
        agent_key="sofia",
        initial_state={
            "mode": "criar",
            "persona_slug": "vz-lupas",
            "source_url": "https://vzlupas.com",
            "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1, "product": 9, "copy": 9, "faq": 9},
        },
        bootstrap_llm=False,
    )
    sid = started.get("session_id") or started.get("id")
    r1 = svc.chat(sid, "extraia os produtos do site 9 produtos 3 grupos de produtos. campanha de retorno da vz lupas mes de junho")
    r2 = svc.chat(sid, "sim crie toda a arvore inspirada na vz lupas, loja jovens de oculos")
    return {"session_id": sid, "r1": r1, "r2": r2}


def _by_type(entries: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in entries:
        out.setdefault(e.get("content_type"), []).append(e)
    return out


def test_start_bootstrap_session_accepts_user_id() -> None:
    started = svc.start_bootstrap_session(
        "gpt-4o-mini",
        initial_context="Missao: teste de ownership",
        agent_key="sofia",
        initial_state={"mode": "legacy"},
        bootstrap_llm=False,
        user_id="user-test-1",
    )
    sid = started.get("session_id") or started.get("id")
    sess = svc.get_session(sid)
    expect(started.get("ok") is not False, "start with user_id does not fail")
    expect(sess.get("user_id") == "user-test-1", "session stores owner user_id")


def test_full_tree_materializes_from_source() -> None:
    with _mocked_backends():
        result = _run_flow()
    r1, r2 = result["r1"], result["r2"]

    expect(r1.get("ok") is True, f"first message did not 500 (ok={r1.get('ok')})")
    expect(r2.get("ok") is True, f"second message did not 500 (ok={r2.get('ok')})")

    # Crawler/source was actually used during message 1.
    sess = svc.get_session(result["session_id"])
    captures = sess.get("crawler_captures") or []
    expect(bool(captures), "crawler ran and captured from the configured source")
    expect(bool(captures[-1].get("product_candidates")), "crawler produced product candidates")

    plan = r2.get("knowledge_plan") or r2.get("proposed_plan") or {}
    entries = plan.get("entries") or []
    expect(bool(entries), "second message materialized a non-empty plan")
    grouped = _by_type(entries)

    expect(len(grouped.get("brand", [])) >= 1, f"brand >= 1 (got {len(grouped.get('brand', []))})")
    expect(len(grouped.get("briefing", [])) >= 1, f"briefing >= 1 (got {len(grouped.get('briefing', []))})")
    expect(len(grouped.get("campaign", [])) >= 1, f"campaign >= 1 (got {len(grouped.get('campaign', []))})")
    expect(len(grouped.get("audience", [])) >= 1, f"audience >= 1 (got {len(grouped.get('audience', []))})")
    expect(len(grouped.get("product_group", [])) == 3, f"product_group == 3 (got {len(grouped.get('product_group', []))})")
    expect(len(grouped.get("product", [])) == 9, f"product == 9 (got {len(grouped.get('product', []))})")
    expect(len(grouped.get("copy", [])) >= 9, f"copy >= 9 (got {len(grouped.get('copy', []))})")
    expect(len(grouped.get("faq", [])) >= 9, f"faq >= 9 (got {len(grouped.get('faq', []))})")

    expect(not (r2.get("plan_violations") or []), f"no blocking violations (got {r2.get('plan_violations')})")
    validation = r2.get("plan_validation") or {}
    expect(validation.get("valid") is True, f"plan validates clean (got {validation})")
    expect(r2.get("stage") == "ready_to_save", f"stage ready_to_save (got {r2.get('stage')})")

    # product_group -> product is well formed (no product hangs off audience).
    by_slug = {e.get("slug"): e for e in entries}
    for product in grouped.get("product", []):
        parent = (product.get("metadata") or {}).get("parent_slug")
        ptype = (by_slug.get(parent) or {}).get("content_type")
        expect(ptype == "product_group", f"product {product.get('slug')!r} hangs off a product_group (got {ptype})")

    # Every entry reaches the persona via parent chain (no orphans).
    remaining_violations = svc.validate_sofia_knowledge_plan(plan, sess)
    expect(not remaining_violations, f"re-validation clean (got {remaining_violations})")


def test_pending_price_marked_not_blocked() -> None:
    """A product without a crawled price must NOT block the tree; it is marked
    pending_price in metadata (HSTN Marrom has no price in the fixture)."""
    with _mocked_backends():
        result = _run_flow()
    plan = result["r2"].get("knowledge_plan") or {}
    products = [e for e in (plan.get("entries") or []) if e.get("content_type") == "product"]
    priced = [p for p in products if (p.get("metadata") or {}).get("price")]
    pending = [p for p in products if (p.get("metadata") or {}).get("pending_price")]
    expect(len(products) == 9, f"9 products built despite a missing price (got {len(products)})")
    expect(len(priced) + len(pending) == len(products), "every product is either priced or pending_price")
    expect(len(pending) >= 1, f"the price-less candidate is flagged pending_price (got {len(pending)})")


def test_trigger_only_fires_on_full_tree_confirmation() -> None:
    # The crawl/extract message must NOT trigger the deterministic builder.
    expect(svc._full_tree_command("extraia os produtos do site 9 produtos 3 grupos de produtos") is False,
           "extract message does not trigger full-tree build")
    expect(svc._full_tree_command("extraia os produtos e copys do site. campanha de inverno. audiencia atacado e varejo") is True,
           "extract products/copy/campaign/audience triggers full-tree build")
    expect(svc._full_tree_command("extraia os produtos do site e monte a estrutura para campanha de inverno") is True,
           "extract + structure request triggers full-tree build after crawl")
    expect(svc._full_tree_command("segmentacao nova de publico atacarejo inverno. briefing para produtos quentes e baratos. 2 produtos do site agrupados") is True,
           "structured source spec with audience/briefing/grouped products triggers full-tree build")
    expect(svc._full_tree_command("sim crie toda a arvore inspirada na vz lupas") is True,
           "confirmation triggers full-tree build")
    expect(svc._full_tree_command("crie a arvore completa") is True, "explicit arvore completa triggers")
    expect(svc._full_tree_command("gere prossiga") is True, "create/proceed confirmation triggers")
    expect(svc._full_tree_command("gere") is True, "single generate command triggers after context/crawler")
    expect(svc._full_tree_command("qual o preco?") is False, "an unrelated question does not trigger")


def test_tock_fatal_two_modal_kits_materialize_in_single_message() -> None:
    prev_router = svc.ModelRouter
    prev_crawl = svc.crawl_catalog_url
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
    svc.crawl_catalog_url = _fake_tock_capture  # type: ignore[assignment]
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        started = svc.start_bootstrap_session(
            "gpt-4o-mini",
            initial_context=(
                "Missao: tock-fatal | Fonte: https://tockfatal.com | "
                "Blocos: briefing, audience, product, campaign, brand, copy, faq"
            ),
            agent_key="sofia",
            initial_state={
                "mode": "criar",
                "persona_slug": "tock-fatal",
                "source_url": "https://tockfatal.com",
                "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1, "product": 2, "copy": 2, "faq": 2},
            },
            bootstrap_llm=False,
        )
        sid = started.get("session_id") or started.get("id")
        response = svc.chat(
            sid,
            "extraia 2 produtos do site. crie um grupo Modais. conecte a audiencia padrao. campanha de inverno tock fatal. aumentar vendas. a fonte e o site tockfatal.com",
        )
    finally:
        svc.ModelRouter = prev_router  # type: ignore[assignment]
        svc.crawl_catalog_url = prev_crawl  # type: ignore[assignment]
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools

    expect(response.get("ok") is True, f"single-message Tock flow did not 500 (ok={response.get('ok')})")
    plan = response.get("knowledge_plan") or response.get("proposed_plan") or {}
    entries = plan.get("entries") or []
    grouped = _by_type(entries)
    titles = {entry.get("title") for entry in grouped.get("product", [])}
    links = {(link.get("source_slug"), link.get("target_slug")) for link in (plan.get("links") or [])}
    brand = grouped.get("brand", [{}])[0]
    briefing = grouped.get("briefing", [{}])[0]
    expect(response.get("stage") == "ready_to_save", f"Tock stage ready_to_save (got {response.get('stage')})")
    expect(brand.get("slug") != "tock-fatal", f"brand slug must not collide with persona slug (got {brand.get('slug')})")
    expect((briefing.get("metadata") or {}).get("parent_slug") == brand.get("slug"),
           f"briefing parent is brand slug (got {(briefing.get('metadata') or {}).get('parent_slug')} vs {brand.get('slug')})")
    expect((brand.get("slug"), briefing.get("slug")) in links,
           f"plan links include brand -> briefing (got {links})")
    expect(len(grouped.get("product_group", [])) == 1, f"Tock product_group == 1 (got {len(grouped.get('product_group', []))})")
    expect(grouped.get("product_group", [{}])[0].get("title") == "Modais", f"Tock product_group title is Modais (got {grouped.get('product_group', [{}])[0].get('title')})")
    expect(len(grouped.get("product", [])) == 2, f"Tock product == 2 (got {len(grouped.get('product', []))})")
    expect("Kit Modal 1 (9 cores disponíveis)" in titles, "Kit Modal 1 is in the generated tree")
    expect("Kit Modal 2 - Urso Estampado" in titles, "Kit Modal 2 is in the generated tree")
    expect(len(grouped.get("copy", [])) >= 2, "Tock modal products have copy cards")
    expect(len(grouped.get("faq", [])) >= 2, "Tock modal products have FAQ cards")
    expect(not (response.get("plan_violations") or []), f"Tock plan has no blocking violations (got {response.get('plan_violations')})")


def test_tock_fatal_structured_spec_prompt_materializes_tree() -> None:
    prev_router = svc.ModelRouter
    prev_crawl = svc.crawl_catalog_url
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
    svc.crawl_catalog_url = _fake_tock_capture  # type: ignore[assignment]
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        started = svc.start_bootstrap_session(
            "gpt-4o-mini",
            initial_context=(
                "Missao: tock-fatal | Fonte: https://tockfatal.com | "
                "Blocos: briefing, audience, product, campaign, brand, copy, faq"
            ),
            agent_key="sofia",
            initial_state={
                "mode": "criar",
                "persona_slug": "tock-fatal",
                "source_url": "https://tockfatal.com",
                "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1, "product": 2, "copy": 2, "faq": 2},
            },
            bootstrap_llm=False,
        )
        sid = started.get("session_id") or started.get("id")
        response = svc.chat(
            sid,
            "segmentacao nova de publico atacarejo inverno. briefing para produtos quentes e baratos. 2 produtos do site agrupados",
        )
    finally:
        svc.ModelRouter = prev_router  # type: ignore[assignment]
        svc.crawl_catalog_url = prev_crawl  # type: ignore[assignment]
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools

    expect(response.get("ok") is True, f"structured Tock prompt did not 500 (ok={response.get('ok')})")
    expect(response.get("stage") == "ready_to_save", f"structured Tock stage ready_to_save (got {response.get('stage')})")
    plan = response.get("knowledge_plan") or response.get("proposed_plan") or {}
    grouped = _by_type(plan.get("entries") or [])
    expect(len(grouped.get("audience", [])) == 1, f"audience == 1 (got {len(grouped.get('audience', []))})")
    expect(len(grouped.get("product_group", [])) == 1, f"product_group == 1 (got {len(grouped.get('product_group', []))})")
    expect(len(grouped.get("product", [])) == 2, f"product == 2 (got {len(grouped.get('product', []))})")
    audience_title = grouped.get("audience", [{}])[0].get("title") or ""
    audience_folded = svc._fold(audience_title)
    expect("atacarejo" in audience_folded, f"audience includes atacarejo (got {audience_title})")
    expect(not (response.get("plan_violations") or []), f"structured Tock plan has no blocking violations (got {response.get('plan_violations')})")


def test_tock_fatal_extract_products_copies_winter_audience_materializes_tree() -> None:
    prev_router = svc.ModelRouter
    prev_crawl = svc.crawl_catalog_url
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
    svc.crawl_catalog_url = _fake_tock_capture  # type: ignore[assignment]
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        started = svc.start_bootstrap_session(
            "gpt-4o-mini",
            initial_context=(
                "Missao: tock-fatal | Fonte: https://tockfatal.com | "
                "Blocos: briefing, audience, product, brand, campaign"
            ),
            agent_key="sofia",
            initial_state={
                "mode": "criar",
                "persona_slug": "tock-fatal",
                "source_url": "https://tockfatal.com",
                "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1, "product": 2},
            },
            bootstrap_llm=False,
        )
        sid = started.get("session_id") or started.get("id")
        response = svc.chat(
            sid,
            "extraia os produtos e copys do site. campanha de inverno. audiencia atacado e varejo. mulheres elegantes, baixo ticket",
        )
    finally:
        svc.ModelRouter = prev_router  # type: ignore[assignment]
        svc.crawl_catalog_url = prev_crawl  # type: ignore[assignment]
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools

    expect(response.get("ok") is True, f"Tock extract/copy message did not 500 (ok={response.get('ok')})")
    expect(response.get("stage") == "ready_to_save", f"Tock extract/copy stage ready_to_save (got {response.get('stage')})")
    plan = response.get("knowledge_plan") or response.get("proposed_plan") or {}
    entries = plan.get("entries") or []
    grouped = _by_type(entries)
    links = {(link.get("source_slug"), link.get("target_slug")) for link in (plan.get("links") or [])}
    expect(len(grouped.get("brand", [])) == 1, f"Tock brand == 1 (got {len(grouped.get('brand', []))})")
    expect(len(grouped.get("briefing", [])) == 1, f"Tock briefing == 1 (got {len(grouped.get('briefing', []))})")
    expect(len(grouped.get("campaign", [])) == 1, f"Tock campaign == 1 (got {len(grouped.get('campaign', []))})")
    expect(len(grouped.get("audience", [])) == 1, f"Tock audience == 1 (got {len(grouped.get('audience', []))})")
    brand = grouped.get("brand", [{}])[0]
    briefing = grouped.get("briefing", [{}])[0]
    campaign = grouped.get("campaign", [{}])[0]
    audience = grouped.get("audience", [{}])[0]
    product_group = grouped.get("product_group", [{}])[0]
    expect(brand.get("slug") != "tock-fatal", f"brand slug must not collide with persona slug (got {brand.get('slug')})")
    expect((brand.get("slug"), briefing.get("slug")) in links, f"links include brand -> briefing (got {links})")
    expect((briefing.get("slug"), campaign.get("slug")) in links, f"links include briefing -> campaign (got {links})")
    expect((campaign.get("slug"), audience.get("slug")) in links, f"links include campaign -> audience (got {links})")
    expect((audience.get("slug"), product_group.get("slug")) in links, f"links include audience -> product_group (got {links})")
    expect(len(grouped.get("product_group", [])) == 1, f"Tock product_group == 1 (got {len(grouped.get('product_group', []))})")
    expect(len(grouped.get("product", [])) == 2, f"Tock product == 2 (got {len(grouped.get('product', []))})")
    expect(len(grouped.get("copy", [])) >= 2, f"Tock copy >= 2 (got {len(grouped.get('copy', []))})")
    expect(len(grouped.get("faq", [])) >= 2, f"Tock faq >= 2 (got {len(grouped.get('faq', []))})")
    audience_title = grouped.get("audience", [{}])[0].get("title") or ""
    audience_folded = svc._fold(audience_title)
    expect("atacado" in audience_folded and "varejo" in audience_folded, f"audience includes atacado/varejo (got {audience_title})")
    expect("mulheres elegantes" in audience_folded, f"audience includes mulheres elegantes (got {audience_title})")
    expect(not (response.get("plan_violations") or []), f"Tock extract/copy plan has no blocking violations (got {response.get('plan_violations')})")


def test_campaign_and_briefing_phrase_does_not_duplicate_campaign_title() -> None:
    prev_router = svc.ModelRouter
    prev_crawl = svc.crawl_catalog_url
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
    svc.crawl_catalog_url = _fake_tock_capture  # type: ignore[assignment]
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        started = svc.start_bootstrap_session(
            "gpt-4o-mini",
            initial_context=(
                "Missao: tock-fatal | Fonte: https://tockfatal.com | "
                "Blocos: briefing, audience, product, brand, campaign, faq"
            ),
            agent_key="sofia",
            initial_state={
                "mode": "criar",
                "persona_slug": "tock-fatal",
                "source_url": "https://tockfatal.com",
                "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1, "product": 2, "faq": 2},
            },
            bootstrap_llm=False,
        )
        sid = started.get("session_id") or started.get("id")
        response = svc.chat(
            sid,
            "crie uma nova audiencia. crie campanha nova. campanha e briefing de venda de modais de inverno. faq sobre preco",
        )
    finally:
        svc.ModelRouter = prev_router  # type: ignore[assignment]
        svc.crawl_catalog_url = prev_crawl  # type: ignore[assignment]
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools

    plan = response.get("knowledge_plan") or response.get("proposed_plan") or {}
    grouped = _by_type(plan.get("entries") or [])
    links = {(link.get("source_slug"), link.get("target_slug")) for link in (plan.get("links") or [])}
    brand = grouped.get("brand", [{}])[0]
    briefing = grouped.get("briefing", [{}])[0]
    campaign = grouped.get("campaign", [{}])[0]
    audience = grouped.get("audience", [{}])[0]
    product_group = grouped.get("product_group", [{}])[0]

    expect(response.get("stage") == "ready_to_save", f"stage ready_to_save (got {response.get('stage')})")
    expect(campaign.get("title") == "Campanha De Venda De Modais De Inverno",
           f"campaign title is normalized (got {campaign.get('title')})")
    expect("Campanha E Briefing" not in (campaign.get("title") or ""),
           f"campaign title does not duplicate briefing intent (got {campaign.get('title')})")
    expect((brand.get("slug"), briefing.get("slug")) in links, f"links include brand -> briefing (got {links})")
    expect((briefing.get("slug"), campaign.get("slug")) in links, f"links include briefing -> campaign (got {links})")
    expect((campaign.get("slug"), audience.get("slug")) in links, f"links include campaign -> audience (got {links})")
    expect((audience.get("slug"), product_group.get("slug")) in links, f"links include audience -> product_group (got {links})")
    expect(len(grouped.get("product", [])) == 2, f"product == 2 (got {len(grouped.get('product', []))})")
    expect(len(grouped.get("faq", [])) >= 2, f"faq >= 2 (got {len(grouped.get('faq', []))})")
    expect(not (response.get("plan_violations") or []), f"plan has no blocking violations (got {response.get('plan_violations')})")


def test_persona_entry_is_implicit_root_not_preview_leaf() -> None:
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        session = {"classification": {"persona_slug": "tock-fatal"}, "persona_slug": "tock-fatal", "messages": []}
        state = svc.normalize_validate_summarize_plan({
            "persona_slug": "tock-fatal",
            "entries": [
                {"content_type": "persona", "slug": "tock-fatal", "title": "tock-fatal", "content": "Persona tock-fatal"},
                {"content_type": "brand", "slug": "tock-fatal-brand", "title": "Tock Fatal", "content": "Marca", "metadata": {"parent_slug": "self"}},
            ],
            "links": [{"source_slug": "tock-fatal", "target_slug": "tock-fatal-brand"}],
        }, session)
    finally:
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools
    entries = state["normalized_plan"].get("entries") or []
    warnings = state["validation"].get("warnings") or []
    expect(not any(entry.get("content_type") == "persona" for entry in entries), "persona entry is removed from plan entries")
    expect(not any("PERSONA ficou sem saida" in warning or "node persona" in warning for warning in warnings), "persona root does not create terminal warning")


def test_default_audience_reuse_does_not_reask_import() -> None:
    session = {
        "persona_id": "persona-1",
        "persona_slug": "tock-fatal",
        "context": "Conecte a audiencia padrao e crie a campanha de inverno.",
        "classification": {"persona_slug": "tock-fatal"},
        "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1},
        "knowledge_plan": {"entries": []},
    }
    persona_context = {
        "audience": [{"slug": "import", "title": "Import"}],
        "brand": [],
        "briefing": [],
        "campaign": [],
        "product": [],
        "offer": [],
        "copy": [],
        "rule": [],
        "asset": [],
        "faq": [],
    }
    review = svc.build_pre_initialization_review(session, persona_context=persona_context)
    questions = review.get("questions") or []
    expect(not any("Import" in q or "import" in q.lower() for q in questions), f"default audience should not re-ask Import (got {questions})")


def test_default_audience_user_message_does_not_reask_closer() -> None:
    session = {
        "persona_id": "persona-1",
        "persona_slug": "tock-fatal",
        "context": "Missao: tock-fatal | Fonte: https://tockfatal.com",
        "classification": {"persona_slug": "tock-fatal"},
        "initial_block_counts": {"brand": 1, "briefing": 1, "campaign": 1, "audience": 1, "product": 2},
        "knowledge_plan": {"entries": []},
        "messages": [
            {
                "role": "user",
                "content": "extraia 2 produtos do site. crie um grupo Modais. conecte a audiencia padrao. campanha de inverno tock fatal.",
            }
        ],
    }
    persona_context = {
        "audience": [{"slug": "closer", "title": "CLOSER"}],
        "brand": [],
        "briefing": [],
        "campaign": [],
        "product": [],
        "offer": [],
        "copy": [],
        "rule": [],
        "asset": [],
        "faq": [],
    }
    review = svc.build_pre_initialization_review(session, persona_context=persona_context)
    questions = review.get("questions") or []
    expect(not any("CLOSER" in q or "closer" in q.lower() for q in questions), f"default audience should not re-ask CLOSER (got {questions})")


def test_count_parsing() -> None:
    sess = {"messages": [
        {"role": "user", "content": "extraia 9 produtos grupo Modais"},
        {"role": "user", "content": "sim crie toda a arvore"},
    ], "crawler_captures": [{"product_candidates": _CANDIDATES}]}
    groups, products = svc._parse_tree_counts(sess)
    expect(groups == 1, f"parsed default 1 group (got {groups})")
    expect(products == 9, f"parsed 9 products (got {products})")
    expect(svc._requested_single_group_title(sess) == "Modais", f"explicit group title parsed as Modais (got {svc._requested_single_group_title(sess)})")


def main() -> int:
    test_trigger_only_fires_on_full_tree_confirmation()
    test_count_parsing()
    test_full_tree_materializes_from_source()
    test_pending_price_marked_not_blocked()
    test_tock_fatal_two_modal_kits_materialize_in_single_message()
    test_tock_fatal_structured_spec_prompt_materializes_tree()
    test_tock_fatal_extract_products_copies_winter_audience_materializes_tree()
    test_campaign_and_briefing_phrase_does_not_duplicate_campaign_title()
    test_default_audience_reuse_does_not_reask_import()
    test_default_audience_user_message_does_not_reask_closer()
    test_persona_entry_is_implicit_root_not_preview_leaf()
    print("PASS test_marketing_criacao_kb_intake_flow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
