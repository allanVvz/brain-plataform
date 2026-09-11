"""A short/icon-only brand mark is an in-progress rollout, not a required
identity field. Unlike `logo_round`/`logo_wordmark`/`logo_reverse` -- whose
absence trips `public_site_contract_incomplete` (503) for the WHOLE
`/api/menu/{slug}` response -- `logo_short` must degrade silently to "absent
from the payload" until a persona actually authors one.
"""
from __future__ import annotations

from routes import menu as menu_route


def _publication_fixture(*, include_logo_short: bool) -> tuple[dict, list[dict]]:
    variants = ["round", "wordmark", "reverse"]
    if include_logo_short:
        variants.append("short")
    asset_nodes = []
    gallery_rows = []
    for suffix, hash_char in zip(variants, "abcd"):
        registry_id = f"registry-{suffix}"
        projection_id = f"projection-{suffix}"
        content_sha256 = hash_char * 64
        asset_nodes.append({
            "id": f"asset:{suffix}", "projection_node_id": projection_id,
            "node_type": "asset", "title": suffix,
            "data": {"asset_id": registry_id, "content_sha256": content_sha256},
        })
        gallery_rows.append({
            "id": registry_id, "persona_id": "persona-id", "knowledge_node_id": projection_id,
            "status": "approved", "approval_status": "approved",
            "url": f"https://storage.example/storage/v1/object/sign/assets-raw/persona-id/{suffix}.png?token=old",
            "storage_bucket": "assets-raw", "storage_path": f"persona-id/{suffix}.png",
            "file_path": f"assets-raw:persona-id/{suffix}.png", "content_sha256": content_sha256,
            "width": 1920, "height": 720,
        })

    identity = {
        "logo_round": {"node_id": "asset:round", "alt": "Logo redondo"},
        "logo_wordmark": {"node_id": "asset:wordmark", "alt": "Wordmark"},
        "logo_reverse": {"node_id": "asset:reverse", "alt": "Logo reverso"},
    }
    if include_logo_short:
        identity["logo_short"] = {"node_id": "asset:short", "alt": "Borboleta"}

    public_site = {
        "slug": "tock-fatal", "name": "Tock Fatal", "format_key": "catalogo_roupas",
        "default_collection_slug": "collection-one", "brand_family": "tock", "brand_channel": "retail",
        "whatsapp": {"phone": "+55 51 99999-0000", "message_template": "Quero saber mais."},
        "identity": identity,
        "pages": [{"node_id": "campaign:linktree"}, {"node_id": "campaign:showcase"}],
        "contacts": [{"node_id": "copy:contact"}],
        "covers": [{"node_id": "asset:round", "position": 0, "focal_point": {"desktop": "full", "mobile": "split-halves"}}],
        "audiences": [{"node_id": "audience:comfort"}],
        "locations": [{"node_id": "campaign:store"}],
    }
    nodes = [{
        "id": "persona:tock", "node_type": "persona", "slug": "tock-fatal",
        "title": "Tock Fatal", "data": {"public_site": public_site},
    }, {
        "id": "gallery:public", "node_type": "gallery", "slug": "public-gallery",
    }, {
        "id": "brand:tock", "node_type": "brand", "slug": "tock-brand",
        "title": "Tock Fatal", "summary": "Brand copy.", "data": {"accent_color": "#9f2960"},
    }, {
        "id": "campaign:linktree", "node_type": "campaign",
        "data": {"page": {
            "route": "/", "kind": "linktree", "title": "Choose a path", "description": "Browse.",
            "actions": [{"id": "showcase", "label": "Browse", "kind": "internal", "href": "/showcase"}],
        }},
    }, {
        "id": "campaign:showcase", "node_type": "campaign",
        "data": {"page": {
            "route": "/showcase", "kind": "showcase", "title": "Style", "description": "Find your style.",
            "cta_label": "Talk to us", "actions": [],
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
    grants = {"brand:tock", "copy:contact", *(node["id"] for node in asset_nodes)}
    edges = [
        {"id": f"edge:publish:{node_id}", "source": node_id, "target": "gallery:public",
         "relation_type": "publishes_to", "metadata": {}}
        for node_id in sorted(grants)
    ]
    publication = {
        "publication_id": "publication-tock", "version": 1, "checksum": "sha256:tock",
        "source": "graph_publication_v3",
        "asset_registry_ids": {row["id"] for row in gallery_rows},
        "granted_node_ids": grants,
        "document": {
            "schema_version": "3.0", "persona": {"id": "persona-id", "slug": "tock-fatal"},
            "nodes": nodes, "edges": edges, "eligible_faq_node_ids": [],
        },
    }
    return publication, gallery_rows


def test_logo_short_appears_when_authored(monkeypatch) -> None:
    publication, gallery_rows = _publication_fixture(include_logo_short=True)
    monkeypatch.setattr(menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows)

    site = menu_route._canonical_site_from_publication(publication, {})

    assert site["identity"]["logo_short"]["asset_id"] == "registry-short"
    # The three required variants must still resolve -- adding the optional
    # fourth key must not disturb them.
    assert site["identity"]["logo_round"]["asset_id"] == "registry-round"


def test_logo_short_absent_does_not_fail_the_whole_site(monkeypatch) -> None:
    publication, gallery_rows = _publication_fixture(include_logo_short=False)
    monkeypatch.setattr(menu_route.supabase_client, "list_assets", lambda **_kwargs: gallery_rows)

    site = menu_route._canonical_site_from_publication(publication, {})

    assert "logo_short" not in site["identity"]
    assert site["identity"]["logo_round"]["asset_id"] == "registry-round"
