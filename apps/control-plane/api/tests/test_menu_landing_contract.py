from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from middleware.auth import is_public_path
from routes import menu as menu_route
from test_menu_logo_short import _publication_fixture


def _landing_publication(monkeypatch) -> dict:
    publication, gallery_rows = _publication_fixture(include_logo_short=False)
    monkeypatch.setattr(menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows)
    nodes = publication["document"]["nodes"]
    nodes.extend([
        {"id": "product:wash", "node_type": "product", "status": "active", "title": "Lavagem"},
        {"id": "rule:process", "node_type": "rule", "status": "validated", "title": "Processo"},
        {"id": "entity:specialist", "node_type": "entity", "status": "approved", "title": "Especialista"},
        {
            "id": "faq:wash", "node_type": "faq", "status": "embedded", "title": "FAQ",
            "data": {"question": "Como funciona?", "answer": "A avaliação é confirmada pelo especialista."},
        },
    ])
    persona = next(node for node in nodes if node["node_type"] == "persona")
    persona["data"]["public_site"]["theme"] = {
        "mode": "dark",
        "colors": {"background": "#050505", "accent": "#ff5a00"},
        "typography": {
            "display": {"family": "Barlow Condensed", "weights": [600, 700]},
            "body": {"family": "Manrope", "weights": [400, 500, 600]},
        },
        "texture": "matte_metal",
    }
    page = next(node for node in nodes if node["id"] == "campaign:showcase")["data"]["page"]
    page.update({
        "route": "/estetica-automotiva",
        "kind": "landing_page",
        "template_key": "automotive_detailing",
        "description": "Objetivo: preservar e revitalizar seu carro.",
        "blocks": [
            {"id": "hero", "kind": "hero", "node_ids": ["campaign:showcase"], "asset_node_ids": ["asset:round"]},
            {"id": "audiences", "kind": "audience_links", "node_ids": ["audience:comfort"]},
            {"id": "services", "kind": "service_catalog", "node_ids": ["product:wash"]},
            {"id": "process", "kind": "process", "node_ids": ["rule:process"]},
            {"id": "gallery", "kind": "gallery", "asset_node_ids": ["asset:round"]},
            {"id": "specialist", "kind": "specialist", "node_ids": ["entity:specialist"], "asset_node_ids": ["asset:round"]},
            {"id": "location", "kind": "location", "node_ids": ["campaign:store"]},
            {"id": "faq", "kind": "faq", "node_ids": ["faq:wash"]},
            {"id": "final", "kind": "final_cta", "node_ids": ["copy:contact"]},
        ],
    })
    home = next(
        node for node in nodes
        if isinstance((node.get("data") or {}).get("page"), dict)
        and node["data"]["page"].get("route") == "/"
    )["data"]["page"]
    home["actions"].append({
        "id": "instagram", "node_id": "brand:tock", "label": "Instagram",
        "description": "Perfil oficial", "kind": "social",
        "href": "https://www.instagram.com/example", "position": 9,
    })
    return publication


def test_landing_page_theme_and_typed_blocks_are_compiled(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)

    site = menu_route._canonical_site_from_publication(publication, {})

    landing = next(page for page in site["pages"] if page["kind"] == "landing_page")
    assert landing["template_key"] == "automotive_detailing"
    assert {block["kind"] for block in landing["blocks"]} == menu_route._SITE_BLOCK_TYPES
    assert landing["blocks"][0]["assets"][0]["asset_id"] == "registry-round"
    faq_block = next(block for block in landing["blocks"] if block["kind"] == "faq")
    assert faq_block["items"] == [{
        "node_id": "faq:wash", "node_type": "faq", "title": "FAQ",
        "question": "Como funciona?", "answer": "A avaliação é confirmada pelo especialista.",
    }]
    assert site["theme"]["typography"]["body"]["family"] == "Manrope"
    assert landing["description"].startswith("Objetivo:")
    assert "internal_commercial_value_band" not in str(site)
    home = next(page for page in site["pages"] if page["route"] == "/")
    instagram = next(action for action in home["actions"] if action["id"] == "instagram")
    assert instagram["kind"] == "social"
    assert instagram["description"] == "Perfil oficial"


def test_editorial_campaign_products_are_projected_from_graph_edges(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)
    publication["document"]["nodes"].append({
        "id": "campaign:editorial-wash", "node_type": "campaign", "status": "approved",
        "title": "Preservacao", "summary": "Cuidados do dia a dia.",
        "data": {"campaign_subtype": "editorial_service_collection", "public_site": {"position": 0}},
    })
    publication["document"].setdefault("edges", []).append({
        "source": "product:wash", "target": "campaign:editorial-wash",
        "relation_type": "part_of_campaign", "metadata": {"active": True, "position": 0},
    })
    page = next(node for node in publication["document"]["nodes"] if node["id"] == "campaign:showcase")
    page["data"]["page"]["blocks"].insert(1, {
        "id": "campaigns", "kind": "campaign_showcase",
        "node_ids": ["campaign:editorial-wash"], "title": "Trilhas de cuidado",
    })
    site = menu_route._canonical_site_from_publication(publication, {})
    landing = next(page for page in site["pages"] if page["kind"] == "landing_page")
    campaign_block = next(block for block in landing["blocks"] if block["kind"] == "campaign_showcase")
    assert campaign_block["campaigns"] == [{
        "node_id": "campaign:editorial-wash", "title": "Preservacao",
        "summary": "Cuidados do dia a dia.", "position": 0,
        "product_node_ids": ["product:wash"],
    }]


@pytest.mark.parametrize("unsafe", ["<script>alert(1)</script>", "javascript:alert(1)", "url(evil.example)"])
def test_landing_blocks_reject_html_css_and_javascript(monkeypatch, unsafe: str) -> None:
    publication = _landing_publication(monkeypatch)
    page = next(node for node in publication["document"]["nodes"] if node["id"] == "campaign:showcase")
    page["data"]["page"]["blocks"][0]["description"] = unsafe

    with pytest.raises(HTTPException) as exc:
        menu_route._canonical_site_from_publication(publication, {})

    assert exc.value.status_code == 503
    assert any("html_css_javascript_forbidden" in error for error in exc.value.detail["errors"])


def test_page_actions_reject_unsafe_authored_text(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)
    page = next(
        node for node in publication["document"]["nodes"]
        if isinstance((node.get("data") or {}).get("page"), dict)
        and node["data"]["page"].get("route") == "/"
    )
    page["data"]["page"]["actions"][-1]["label"] = "<style>body{display:none}</style>"

    with pytest.raises(HTTPException) as exc:
        menu_route._canonical_site_from_publication(publication, {})

    assert any("html_css_javascript_forbidden" in error for error in exc.value.detail["errors"])


def test_landing_rejects_inactive_or_cross_persona_references(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)
    product = next(node for node in publication["document"]["nodes"] if node["id"] == "product:wash")
    product.update({"status": "draft", "persona_id": "another-persona"})

    with pytest.raises(HTTPException) as exc:
        menu_route._canonical_site_from_publication(publication, {})

    assert any("not_active_published_or_scoped" in error for error in exc.value.detail["errors"])


@pytest.mark.parametrize("node_id", ["copy:contact", "asset:round", "audience:comfort", "campaign:store"])
def test_public_site_root_rejects_inactive_or_cross_persona_references(monkeypatch, node_id: str) -> None:
    publication = _landing_publication(monkeypatch)
    node = next(node for node in publication["document"]["nodes"] if node["id"] == node_id)
    node.update({"status": "draft", "persona_id": "another-persona"})

    with pytest.raises(HTTPException) as exc:
        menu_route._canonical_site_from_publication(publication, {})

    assert any("not_active_published_or_scoped" in error for error in exc.value.detail["errors"])


def test_automotive_site_requires_distinct_quick_and_human_channels(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)
    contact = next(node for node in publication["document"]["nodes"] if node["id"] == "copy:contact")
    contact["data"]["contact"]["key"] = "human"

    with pytest.raises(HTTPException) as exc:
        menu_route._canonical_site_from_publication(publication, {})

    assert "site.contacts.human.phone:must_differ_from_quick_booking" in exc.value.detail["errors"]


def test_event_validation_rejects_pii_fields_and_accepts_published_nodes(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)
    monkeypatch.setattr(menu_route, "_resolve_persona", lambda _slug: {"id": "persona-id", "slug": "tock-fatal"})
    monkeypatch.setattr(menu_route, "_active_publication_context", lambda *_args: publication)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1)})
    body = {
        "event_type": "service_interest",
        "session_id": "anonymous_session_1234",
        "page_route": "/estetica-automotiva",
        "publication_id": "publication-tock",
        "graph_checksum": "sha256:tock",
        "node_ids": ["product:wash"],
        "utm": {"source": "instagram", "campaign": "regional"},
    }

    persona, event = menu_route._validated_public_site_event("tock-fatal", body, request)

    assert persona["id"] == "persona-id"
    assert event["payload"]["utm_source"] == "instagram"
    with pytest.raises(HTTPException) as exc:
        menu_route._validated_public_site_event("tock-fatal", {**body, "phone": "+555199999999"}, request)
    assert exc.value.detail["code"] == "public_site_event_fields_unsupported"
    with pytest.raises(HTTPException) as exc:
        menu_route._validated_public_site_event(
            "tock-fatal", {**body, "utm": {"campaign": "contact +55 51 99999-0000"}}, request
        )
    assert exc.value.detail["code"] == "public_site_event_utm_invalid"


def test_event_persistence_is_best_effort_and_contains_no_free_form_content(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        menu_route, "_validated_public_site_event",
        lambda *_args: ({"id": "persona-id"}, {
            "event_type": "page_impression",
            "payload": {
                "session_id": "anonymous_session_1234", "page_route": "/",
                "publication_id": "publication-id", "graph_checksum": "sha256:abc", "node_ids": [],
            },
        }),
    )
    monkeypatch.setattr(menu_route.supabase_client, "insert_event", lambda row: captured.update(row) or None)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    result = menu_route.post_api_menu_event("tock-fatal", request, {})

    assert result == {"ok": True, "accepted": True, "persisted": False}
    assert captured["event_type"] == "public_site.page_impression"
    assert not ({"name", "phone", "message", "content"} & set(captured["payload"]))


def test_events_auth_allowlist_is_method_exact() -> None:
    assert is_public_path("/api/menu/utzig-garage/events", "POST")
    assert is_public_path("/api/menu/utzig-garage/intent", "POST")
    assert not is_public_path("/api/menu/utzig-garage/intent", "GET")
    assert not is_public_path("/api/menu/utzig-garage/events", "GET")
    assert not is_public_path("/api/menu/utzig-garage/admin-assets", "POST")


def test_intent_code_requires_graph_intent_and_durable_event(monkeypatch) -> None:
    publication = _landing_publication(monkeypatch)
    audience = next(node for node in publication["document"]["nodes"] if node["id"] == "audience:comfort")
    audience["tags"] = ["vehicle_journey_intent"]
    monkeypatch.setattr(menu_route, "_resolve_persona", lambda _slug: {"id": "persona-id"})
    monkeypatch.setattr(menu_route, "_active_publication_context", lambda *_args: publication)
    captured = {}
    monkeypatch.setattr(menu_route.supabase_client, "insert_event", lambda row: captured.update(row) or {"id": "event-1"})
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1)})
    body = {
        "session_id": "anonymous_session_1234", "page_route": "/estetica-automotiva",
        "publication_id": "publication-tock", "graph_checksum": "sha256:tock",
        "audience_node_id": "audience:comfort",
    }
    result = menu_route.post_api_menu_intent("tock-fatal", request, body)
    assert result["code"].startswith("BI-")
    assert result["code"] not in str(captured)
    assert captured["persona_id"] == "persona-id"
    assert captured["payload"]["audience_node_id"] == "audience:comfort"
    assert len(captured["payload"]["code_hash"]) == 64

    audience["tags"] = []
    with pytest.raises(HTTPException) as exc:
        menu_route.post_api_menu_intent("tock-fatal", request, body)
    assert exc.value.detail["code"] == "public_site_intent_not_published"

    audience["tags"] = ["vehicle_journey_intent"]
    monkeypatch.setattr(menu_route.supabase_client, "insert_event", lambda _row: None)
    with pytest.raises(HTTPException) as exc:
        menu_route.post_api_menu_intent("tock-fatal", request, body)
    assert exc.value.status_code == 503
