from copy import deepcopy

import pytest
from brain_contracts.catalog_media import resolve_catalog_media, validate_image_selection


def fixture():
    nodes = [{"id": key, "node_type": kind, "persona_id": "p", "data": data}
             for key, kind, data in [("g", "product_group", {}), ("sub", "category", {}),
                 ("p", "product", {}), ("a", "asset", {"media": {"url": "https://cdn.example/a.jpg"}}),
                 ("b", "asset", {"media": {"url": "https://cdn.example/b.jpg"}})]]
    edges = [{"id": str(i), "source": s, "target": t, "relation_type": "contains",
              "metadata": {"media_assignment": {"assigned_at": date}}}
             for i, (s, t, date) in enumerate([("g", "sub", ""), ("sub", "p", ""),
                 ("p", "a", "2026-09-01T00:00:00Z"), ("p", "b", "2026-09-02T00:00:00Z")])]
    return nodes, edges


def resolve(nodes, edges, owner="g", **kwargs):
    return resolve_catalog_media(nodes, edges, persona_id="p", scoped_ids={n["id"] for n in nodes},
                                 owner_id=owner, publication={"id": "v1"}, **kwargs)


def test_recursive_latest_and_legacy_category():
    nodes, edges = fixture()
    result = resolve(nodes, edges)
    assert [a["node_id"] for a in result["assets"]] == ["b", "a"]
    assert result["cover_origin"]["kind"] == "inherited"
    assert resolve(nodes, edges, "sub")["cover"]["node_id"] == "b"


def test_pin_unpin_direct_and_unavailable():
    nodes, edges = fixture()
    edges[-2]["metadata"]["media_assignment"]["pinned"] = True
    assert resolve(nodes, edges, "p")["cover"]["node_id"] == "a"
    assert resolve(nodes, edges)["cover"]["node_id"] == "b"  # child's pin is not the group's
    edges[-2]["metadata"]["media_assignment"]["pinned"] = False
    assert resolve(nodes, edges, "p")["cover"]["node_id"] == "b"
    assert resolve(nodes, edges, "p", available=lambda a: a["node_id"] != "b")["cover"]["node_id"] == "a"
    edges.append({"source": "g", "target": "a", "relation_type": "uses_asset"})
    assert resolve(nodes, edges)["cover_origin"]["kind"] == "direct"
    edges[-1]["metadata"] = {"active": False}
    assert resolve(nodes, edges)["cover"]["node_id"] == "b"


@pytest.mark.parametrize("excluded", ["persona", "inbound", "logo", "font", "unavailable"])
def test_excludes_foreign_and_noncommercial_media(excluded):
    nodes, edges = fixture()
    b = nodes[-1]
    if excluded == "persona": b["persona_id"] = "foreign"
    if excluded == "inbound": b["data"]["lead_ref"] = 123
    if excluded == "logo": b["data"]["asset_function"] = "brand_logo"
    if excluded == "font": b["data"]["mime_type"] = "font/woff2"
    if excluded == "unavailable": b["data"]["media"]["available"] = False
    assert resolve(nodes, edges)["cover"]["node_id"] == "a"


def test_scope_cycle_tie_and_order_independent():
    nodes, edges = fixture()
    edges[-1]["metadata"] = deepcopy(edges[-2]["metadata"])
    edges.append({"source": "sub", "target": "g", "relation_type": "contains"})
    assert resolve(nodes, edges) == resolve(list(reversed(nodes)), list(reversed(edges)))
    result = resolve_catalog_media(nodes, edges, persona_id="p", scoped_ids={"g", "sub", "p", "a"}, owner_id="g")
    assert [a["node_id"] for a in result["assets"]] == ["a"]


def test_model_selection_rejects_stale_duplicate_out_of_scope_and_over_limit():
    nodes, edges = fixture()
    assets = resolve(nodes, edges)["assets"]
    choice = {"asset_node_id": "b", "caption": "Model caption"}
    assert validate_image_selection([choice], assets, publication={"id": "v1"})[0]["caption"] == "Model caption"
    for choices, version, limit in [([choice] * 4, "v1", 3), ([choice] * 2, "v1", 3),
                                   ([choice], "v2", 3), ([choice], "v1", 0),
                                   ([{"asset_node_id": "foreign"}], "v1", 3)]:
        with pytest.raises(ValueError):
            validate_image_selection(choices, assets, publication={"id": version}, max_images=limit)


def test_opt_in_public_fallback_is_positioned_curated_and_never_repeats_as_direct_asset():
    nodes, edges = fixture()
    nodes.extend([
        {"id": "gallery", "node_type": "gallery", "persona_id": "p", "data": {}},
        {"id": "campaign", "node_type": "campaign", "persona_id": "p", "data": {}},
        {"id": "fallback", "node_type": "asset", "persona_id": "p", "data": {"media": {"url": "https://cdn.example/fallback.jpg"}}},
    ])
    # Direct product evidence wins regardless of the edge list's upload dates.
    for edge in edges:
        if edge["source"] == "p":
            edge["metadata"]["media_assignment"]["position"] = 9 if edge["target"] == "a" else 1
        if edge["target"] in {"a", "b"}:
            edges.append({"source": edge["target"], "target": "gallery", "relation_type": "gallery_asset"})
    edges.extend([
        {"id": "group-cover", "source": "g", "target": "fallback", "relation_type": "category_has_asset",
         "metadata": {"media_assignment": {"position": 0, "fallback_allowed": True}}},
        {"source": "fallback", "target": "gallery", "relation_type": "gallery_asset"},
        {"id": "campaign-cover", "source": "campaign", "target": "fallback", "relation_type": "campaign_has_asset",
         "metadata": {"media_assignment": {"position": 0, "fallback_allowed": True}}},
    ])
    scoped = {node["id"] for node in nodes}
    policy = {"enabled": True, "campaign_id": "campaign"}
    product = resolve_catalog_media(nodes, edges, persona_id="p", scoped_ids=scoped, owner_id="p", fallback_policy=policy)
    assert [item["node_id"] for item in product["assets"]] == ["b", "a"]
    assert product["media"]["primary"]["origin"] == "product"
    # No product evidence: group cover is representative and does not enter
    # legacy direct assets, which lets a grouped catalog render it once.
    without_direct = [edge for edge in edges if not (edge.get("source") == "p" and edge.get("target") in {"a", "b"})]
    fallback = resolve_catalog_media(nodes, without_direct, persona_id="p", scoped_ids=scoped, owner_id="p", fallback_policy=policy)
    assert fallback["assets"] == []
    assert fallback["media"]["primary"]["origin"] == "group"
    assert fallback["media"]["primary"]["representative"] is True


def test_opt_in_public_fallback_rejects_asset_without_gallery_or_position():
    nodes, edges = fixture()
    nodes.append({"id": "campaign", "node_type": "campaign", "persona_id": "p", "data": {}})
    edges.append({"source": "campaign", "target": "a", "relation_type": "campaign_has_asset",
                  "metadata": {"media_assignment": {"fallback_allowed": True}}})
    result = resolve_catalog_media(nodes, edges, persona_id="p", scoped_ids={n["id"] for n in nodes}, owner_id="p",
                                   fallback_policy={"enabled": True, "campaign_id": "campaign"})
    assert result["media"]["primary"] is None
