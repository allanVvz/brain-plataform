from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import menu as menu_route  # noqa: E402


def _canonical_publication_fixture() -> tuple[dict, list[dict]]:
    asset_nodes = []
    gallery_rows = []
    for suffix, hash_char in zip(("round", "wordmark", "reverse", "cover", "product"), "abcde"):
        registry_id = f"registry-{suffix}"
        projection_id = f"projection-{suffix}"
        content_sha256 = hash_char * 64
        asset_nodes.append({
            "id": f"asset:{suffix}",
            "projection_node_id": projection_id,
            "node_type": "asset",
            "title": suffix,
            "data": {"asset_id": registry_id, "content_sha256": content_sha256},
        })
        gallery_rows.append({
            "id": registry_id,
            "persona_id": "persona-id",
            "knowledge_node_id": projection_id,
            "status": "approved",
            "approval_status": "approved",
            "url": f"https://storage.example/storage/v1/object/sign/assets-raw/persona-id/{suffix}.png?token=old",
            "storage_bucket": "assets-raw",
            "storage_path": f"persona-id/{suffix}.png",
            "file_path": f"assets-raw:persona-id/{suffix}.png",
            "content_sha256": content_sha256,
            "width": 1920,
            "height": 720,
        })
    public_site = {
        "slug": "generic-store",
        "name": "Generic Store",
        "format_key": "catalogo_roupas",
        "default_collection_slug": "collection-one",
        "brand_family": "generic-family",
        "brand_channel": "retail",
        "whatsapp": {"phone": "+55 51 99999-0000", "message_template": "Quero saber mais."},
        "identity": {
            "logo_round": {"node_id": "asset:round", "alt": "Logo redondo"},
            "logo_wordmark": {"node_id": "asset:wordmark", "alt": "Wordmark"},
            "logo_reverse": {"node_id": "asset:reverse", "alt": "Logo reverso"},
        },
        "pages": [{"node_id": "campaign:linktree"}, {"node_id": "campaign:showcase"}],
        "contacts": [{"node_id": "copy:contact"}],
        "covers": [{
            "node_id": "asset:cover", "position": 0,
            "focal_point": {"desktop": "full", "mobile": "split-halves"},
        }],
        "audiences": [{"node_id": "audience:comfort"}],
        "locations": [{"node_id": "campaign:store"}],
    }
    nodes = [{
        "id": "persona:generic",
        "node_type": "persona",
        "slug": "generic",
        "title": "Published Persona",
        "data": {"public_site": public_site},
    }, {
        "id": "gallery:public", "node_type": "gallery", "slug": "public-gallery",
    }, {
        "id": "brand:generic", "node_type": "brand", "slug": "published-brand",
        "title": "Published Brand", "summary": "Published brand copy.",
        "data": {"accent_color": "#9f2960"},
    }, {
        "id": "group:published", "node_type": "product_group", "slug": "published-group",
        "title": "Published Group", "data": {
            "position": 1,
            "cta": {"label": "Conhecer este estilo", "message_template": "Quero conhecer este estilo."},
        },
    }, {
        "id": "product:published", "node_type": "product", "slug": "published-product",
        "title": "Published Product", "summary": "Published description.", "data": {
            "position": 1, "price": {"amount": 79.9, "currency": "BRL"},
            "cta": {"label": "Eu quero!", "message_template": "Quero ver este produto."},
        },
    }, {
        "id": "copy:product", "node_type": "copy", "slug": "published-product-copy",
        "summary": "Published product copy.", "data": {"slot": "body"},
    }, {
        "id": "faq:product", "node_type": "faq", "slug": "published-product-faq",
        "title": "Como comprar?", "data": {"question": "Como comprar?", "answer": "Fale com a equipe."},
    }, {
        "id": "campaign:collection", "node_type": "campaign", "slug": "collection-one",
        "title": "Published Collection", "data": {},
    }, {
        "id": "campaign:linktree",
        "node_type": "campaign",
        "data": {"page": {
            "route": "/", "kind": "linktree", "title": "Choose a path",
            "description": "Browse or talk to us.",
            "actions": [{"id": "showcase", "label": "Browse", "kind": "internal", "href": "/showcase"}],
        }},
    }, {
        "id": "campaign:showcase",
        "node_type": "campaign",
        "data": {"page": {
            "route": "/showcase", "kind": "showcase", "eyebrow": "New",
            "title": "Your style", "description": "Find what fits you.", "cta_label": "Talk to us",
            "ribbon_terms": ["Soft", "Modern"], "actions": [],
            "sections": {
                "audiences": {"eyebrow": "For you", "title": "Find your moment"},
                "groups": {
                    "eyebrow": "Styles", "title": "Explore", "item_eyebrow": "Selection",
                    "item_description": "Pieces selected for this style.",
                },
                "final_cta": {"title": "Need help?", "description": "Talk to our team.", "action_label": "Chat"},
            },
        }},
    }, {
        "id": "copy:contact", "node_type": "copy",
        "data": {"contact": {
            "key": "sales", "label": "Talk to Sales", "phone": "5551999990000",
            "message_template": "I need help.", "position": 0,
        }},
    }, {
        "id": "audience:comfort", "node_type": "audience",
        "data": {"audience": {"label": "Comfort", "message_template": "Show me comfortable pieces.", "position": 0}},
    }, {
        "id": "campaign:store", "node_type": "campaign",
        "data": {
            "metadata": {"campaign_subtype": "physical_store"},
            "location": {
                "label": "Our store", "address": "Main Street, 100",
                "coordinates": {"latitude": -29.9, "longitude": -51.1},
                "validation_status": "validated", "google_maps_url": "https://maps.google.com/example",
                "ui_theme": {"marker_color": "#9f2960"},
                "map": {"style_url": "https://tiles.example/style.json", "zoom": 15.5, "min_zoom": 11, "max_zoom": 18},
            },
        },
    }, *asset_nodes]
    grants = {
        "brand:generic", "group:published", "product:published", "copy:product", "faq:product",
        *(node["id"] for node in asset_nodes),
    }
    edges = [
        *({
            "id": f"edge:publish:{node_id}", "source": node_id, "target": "gallery:public",
            "relation_type": "publishes_to", "metadata": {},
        } for node_id in sorted(grants)),
        {
            "id": "edge:group-product", "source": "group:published", "target": "product:published",
            "relation_type": "product_group_has_product", "metadata": {},
        },
        {
            "id": "edge:product-asset", "source": "product:published", "target": "asset:product",
            "relation_type": "uses_asset",
            "metadata": {"page_binding": {"slot_key": "product_image:published-product", "position": 0}},
        },
        {
            "id": "edge:copy-product", "source": "copy:product", "target": "product:published",
            "relation_type": "supports_copy", "metadata": {},
        },
        {
            "id": "edge:faq-product", "source": "faq:product", "target": "product:published",
            "relation_type": "answers_question", "metadata": {},
        },
    ]
    publication = {
        "publication_id": "publication-site",
        "version": 1,
        "checksum": "sha256:site",
        "source": "graph_publication_v3",
        "asset_registry_ids": {row["id"] for row in gallery_rows},
        "granted_node_ids": grants,
        "document": {
            "schema_version": "3.0", "persona": {"id": "persona-id", "slug": "generic"},
            "nodes": nodes, "edges": edges, "eligible_faq_node_ids": ["faq:product"],
        },
    }
    return publication, gallery_rows


def test_active_graphbundle_publication_is_the_public_grant_authority(monkeypatch) -> None:
    publication = {
        "id": "publication-28",
        "persona_id": "persona-1",
        "version": 28,
        "checksum": "sha256:active-v28",
        "document_json": {
            "schema_version": "3.0",
            "persona": {"id": "persona-1", "slug": "persona"},
            "nodes": [
                {"id": "gallery:default", "node_type": "gallery", "slug": "gallery-default"},
                {"id": "product:one", "node_type": "product", "slug": "product-one"},
                {
                    "id": "asset:one",
                    "node_type": "asset",
                    "slug": "asset-one",
                    "data": {"asset_id": "asset-registry-1"},
                },
            ],
            "edges": [
                {
                    "id": "edge:product-public",
                    "source": "product:one",
                    "target": "gallery:default",
                    "relation_type": "publishes_to",
                },
                {
                    "id": "edge:asset-public",
                    "source": "asset:one",
                    "target": "gallery:default",
                    "relation_type": "publishes_to",
                },
            ],
        },
    }
    monkeypatch.setattr(
        menu_route.supabase_client,
        "get_active_graph_publication",
        lambda persona_id: publication if persona_id == "persona-1" else None,
    )
    monkeypatch.setattr(
        menu_route.graph_json_v2_store,
        "load_current",
        lambda _slug: (_ for _ in ()).throw(AssertionError("legacy graph must not be read")),
    )

    context = menu_route._public_graph_context("persona", "persona-1")

    assert context["source"] == "graph_publication_v3"
    assert context["publication_id"] == "publication-28"
    assert context["allowed"]["product"] == {"product-one"}
    assert context["asset_registry_ids"] == {"asset-registry-1"}
    assert context["action_node_id"] == "gallery:default"


def test_product_assets_use_canonical_slot_and_deduplicate_asset_id(monkeypatch) -> None:
    gallery_assets = [
        {
            "id": "asset-registry-1",
            "knowledge_node_id": "asset-node-1",
            "status": "approved",
            "url": "https://cdn.example/one.jpg",
        },
        {
            "id": "asset-registry-2",
            "knowledge_node_id": "asset-node-2",
            "status": "approved",
            "url": "https://cdn.example/two.jpg",
        },
    ]
    edges = [
        {
            "id": "edge:legacy",
            "source_node_id": "product-1",
            "target_node_id": "asset-node-1",
            "relation_type": "product_image",
            "metadata": {},
        },
        {
            "id": "edge:canonical",
            "source_node_id": "product-1",
            "target_node_id": "asset-node-1",
            "relation_type": "uses_asset",
            "metadata": {
                "role": "product_image",
                "page_binding": {
                    "slot_key": "product_image:product-one",
                    "position": 1,
                },
            },
        },
        {
            "id": "edge:generic-use",
            "source_node_id": "product-1",
            "target_node_id": "asset-node-2",
            "relation_type": "uses_asset",
            "metadata": {"role": "supporting_document"},
        },
    ]
    monkeypatch.setattr(
        menu_route.supabase_client,
        "list_gallery_assets",
        lambda **_kwargs: gallery_assets,
    )
    monkeypatch.setattr(
        menu_route.supabase_client,
        "list_edges_for_nodes",
        lambda *_args, **_kwargs: edges,
    )

    resolved = menu_route._product_assets([{"id": "product-1"}], "persona-1")

    assert len(resolved["product-1"]) == 1
    assert resolved["product-1"][0]["id"] == "asset-registry-1"
    assert resolved["product-1"][0]["_edge"]["id"] == "edge:canonical"


def test_public_bucket_uses_stable_url_and_private_bucket_keeps_signed_url(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_PUBLIC_URL", "https://storage.example")
    public_asset = {
        "url": "https://storage.example/storage/v1/object/sign/assets-raw/products/photo.jpg?token=temporary",
        "file_path": "assets-raw:products/photo one.jpg",
    }
    private_asset = {
        "url": "https://storage.example/storage/v1/object/sign/whatsapp-inbound/private.jpg?token=temporary",
        "file_path": "whatsapp-inbound:private.jpg",
    }

    assert menu_route._asset_url(public_asset) == (
        "https://storage.example/storage/v1/object/public/assets-raw/products/photo%20one.jpg"
    )
    assert menu_route._asset_url(private_asset) == private_asset["url"]
    assert menu_route._stable_public_asset_url(private_asset) == ""


def test_canonical_site_is_projected_from_active_graphbundle_only(monkeypatch) -> None:
    publication, gallery_rows = _canonical_publication_fixture()
    monkeypatch.setattr(
        menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows,
    )

    site = menu_route._canonical_site_from_publication(publication, {})

    assert site["brand_family"] == "generic-family"
    assert site["brand_channel"] == "retail"
    assert site["identity"]["logo_round"]["asset_id"] == "registry-round"
    assert [page["route"] for page in site["pages"]] == ["/", "/showcase"]
    assert site["pages"][1]["sections"]["groups"]["item_eyebrow"] == "Selection"
    assert site["contacts"][0]["node_id"] == "copy:contact"
    assert site["covers"][0]["content_sha256"] == "d" * 64
    assert site["audiences"][0]["node_id"] == "audience:comfort"
    assert site["locations"][0]["coordinates"] == {"latitude": -29.9, "longitude": -51.1}
    assert site["whatsapp"]["href"].startswith("https://wa.me/5551999990000")


def test_active_graphbundle_with_incomplete_site_fails_closed(monkeypatch) -> None:
    publication, gallery_rows = _canonical_publication_fixture()
    persona = next(node for node in publication["document"]["nodes"] if node["node_type"] == "persona")
    del persona["data"]["public_site"]["identity"]["logo_round"]
    monkeypatch.setattr(
        menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows,
    )

    try:
        menu_route._canonical_site_from_publication(publication, {})
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
        assert exc.detail["code"] == "public_site_contract_incomplete"
        assert "asset_node_missing:empty" in exc.detail["errors"]
    else:
        raise AssertionError("incomplete active public_site must fail closed")


def test_active_graphbundle_requires_default_collection_slug(monkeypatch) -> None:
    publication, gallery_rows = _canonical_publication_fixture()
    persona = next(node for node in publication["document"]["nodes"] if node["node_type"] == "persona")
    del persona["data"]["public_site"]["default_collection_slug"]
    monkeypatch.setattr(menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows)

    try:
        menu_route._canonical_site_from_publication(publication, {})
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
        assert "site.default_collection_slug:required" in exc.detail["errors"]
    else:
        raise AssertionError("v3 must not derive collection from persona config")


def test_active_publication_lookup_error_never_falls_back_to_legacy(monkeypatch) -> None:
    def fail_lookup(_persona_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(menu_route.supabase_client, "get_active_graph_publication", fail_lookup)
    monkeypatch.setattr(
        menu_route.graph_json_v2_store, "load_current",
        lambda _slug: (_ for _ in ()).throw(AssertionError("legacy fallback is forbidden on lookup failure")),
    )

    try:
        menu_route._public_graph_context("generic", "persona-id")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
        assert exc.detail["code"] == "graph_publication_lookup_failed"
    else:
        raise AssertionError("publication lookup failure must fail closed")


def test_active_publication_rejects_persona_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(menu_route.supabase_client, "get_active_graph_publication", lambda _persona_id: {
        "id": "publication-wrong", "persona_id": "another-persona", "version": 3,
        "checksum": "sha256:wrong",
        "document_json": {
            "schema_version": "3.0", "persona": {"id": "another-persona", "slug": "other"},
            "nodes": [], "edges": [],
        },
    })

    try:
        menu_route._public_graph_context("generic", "persona-id")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
        assert exc.detail["code"] == "graph_publication_identity_invalid"
        assert "publication.persona_id:mismatch" in exc.detail["errors"]
        assert "document.persona.slug:mismatch" in exc.detail["errors"]
    else:
        raise AssertionError("a publication cannot cross persona boundaries")


def test_active_site_rejects_private_or_signed_asset(monkeypatch) -> None:
    publication, gallery_rows = _canonical_publication_fixture()
    cover = next(row for row in gallery_rows if row["id"] == "registry-cover")
    cover["storage_bucket"] = "whatsapp-inbound"
    cover["file_path"] = "whatsapp-inbound:persona-id/cover.png"
    monkeypatch.setattr(menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows)

    try:
        menu_route._canonical_site_from_publication(publication, {})
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
        assert "site.covers[0].url:stable_public_https_required" in exc.detail["errors"]
    else:
        raise AssertionError("private asset URL must not be exposed publicly")


def test_v3_asset_registry_requires_top_level_approval(monkeypatch) -> None:
    monkeypatch.setattr(menu_route.supabase_client, "list_assets", lambda **_kwargs: [{
        "id": "asset-pending", "persona_id": "persona-id", "status": "ready",
        "approval_status": "pending",
        "metadata": {"validation_status": "approved"},
        "storage_bucket": "assets-raw", "storage_path": "persona-id/pending.png",
        "url": "https://storage.example/storage/v1/object/sign/assets-raw/persona-id/pending.png?token=old",
    }])

    assert menu_route._published_assets_by_registry(
        "persona-id", {"asset-pending"}, cache={},
    ) == {}


def test_catalog_cta_is_owned_by_compiled_graph_node() -> None:
    node = {
        "id": "product:one",
        "data": {"public_site": {"cta": {"label": "I want it", "message_template": "Show me this product."}}},
    }

    assert menu_route._site_cta(node) == {
        "node_id": "product:one",
        "label": "I want it",
        "message_template": "Show me this product.",
    }


def test_public_catalog_requires_group_and_media_product_ctas() -> None:
    errors = menu_route._catalog_cta_errors([{
        "id": "group:one",
        "cta": None,
        "products": [
            {"id": "product:with-image", "assets": [{"id": "asset:one"}], "cta": None},
            {"id": "product:without-image", "assets": [], "cta": None},
        ],
    }])

    assert errors == [
        "group:one:cta_required",
        "product:with-image:cta_required",
    ]


def test_public_messages_reject_technical_node_ids() -> None:
    errors: list[str] = []
    value = menu_route._required_natural_message(
        {"message_template": "Gostei do product:internal-123"},
        "message_template",
        "site.whatsapp",
        errors,
    )

    assert value == "Gostei do product:internal-123"
    assert errors == ["site.whatsapp.message_template:technical_id_forbidden"]
    assert menu_route._site_cta({
        "id": "product:one",
        "data": {"cta": {"label": "Quero", "message_template": "produto product:one"}},
    }) is None


def test_menu_endpoint_does_not_read_persona_public_site_config_when_v3_is_active(monkeypatch) -> None:
    publication, gallery_rows = _canonical_publication_fixture()
    monkeypatch.setattr(menu_route, "_public_graph_context", lambda *_args: publication)
    monkeypatch.setattr(menu_route.supabase_client, "get_persona", lambda _slug: {
        "id": "persona-id", "slug": "generic", "name": "Generic",
        "config": {"public_site": {"site_name": "STALE CONFIG MUST NOT WIN"}},
    })
    monkeypatch.setattr(
        menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows,
    )
    def staged_state_must_not_be_read(*_args, **_kwargs):
        raise AssertionError("staged knowledge state must not affect an active v3 snapshot")

    monkeypatch.setattr(menu_route.supabase_client, "list_gallery_assets", staged_state_must_not_be_read)
    monkeypatch.setattr(menu_route.supabase_client, "get_knowledge_node_by_slug", staged_state_must_not_be_read)
    monkeypatch.setattr(menu_route.supabase_client, "list_product_collection_nodes", staged_state_must_not_be_read)
    monkeypatch.setattr(menu_route.supabase_client, "list_product_nodes", staged_state_must_not_be_read)
    monkeypatch.setattr(menu_route.supabase_client, "list_edges_for_nodes", staged_state_must_not_be_read)
    monkeypatch.setattr(menu_route.supabase_client, "list_knowledge_nodes_by_ids", staged_state_must_not_be_read)
    monkeypatch.setattr(
        menu_route, "_brand_payload",
        staged_state_must_not_be_read,
    )
    monkeypatch.setattr(menu_route, "_collection_campaign_assets", staged_state_must_not_be_read)
    monkeypatch.setattr(menu_route, "_collection_briefing", staged_state_must_not_be_read)
    monkeypatch.setattr(
        menu_route.supabase_client,
        "list_public_site_formats",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy format registry read")),
    )
    monkeypatch.setattr(
        menu_route.public_site,
        "public_site_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("persona config fallback")),
    )

    payload = menu_route.build_menu_payload("generic")

    assert payload["site"]["name"] == "Generic Store"
    assert payload["site"]["brand_family"] == "generic-family"
    assert payload["publication_id"] == "publication-site"
    assert payload["persona"]["name"] == "Published Persona"
    assert payload["persona"]["brand"]["name"] == "Published Brand"
    category = payload["persona"]["collections"][0]["categories"][0]
    product = category["products"][0]
    assert category["title"] == "Published Group"
    assert product["name"] == "Published Product"
    assert product["description"] == "Published description."
    assert product["offer"] == {"amount": 79.9, "currency": "BRL"}
    assert product["assets"][0]["url"] == (
        "https://storage.example/storage/v1/object/public/assets-raw/persona-id/product.png"
    )
    assert product["copies"][0]["slug"] == "published-product-copy"
    assert product["faqs"][0]["slug"] == "published-product-faq"
    assert product["faqs"][0]["is_rag_eligible"] is True
