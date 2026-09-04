"""Declarative block templates for the public site output.

A public page is a list of *blocks*. Each block declares where its content comes
from in the graph -- a node type plus named relations -- instead of being wired
in Python. One resolver serves every format, so a new page shape is a new
template row, not new code.

Two rules make this safe:

1. **Scope is a branch anchor.** Every template carries ``scope``: the id of a
   node with the ``branch_anchor`` capability. Only nodes inside that branch's
   closure may reach the payload. Tock Fatal sells the same 73 products under
   two brands at different prices; without this, a retail page could emit a
   wholesale price. The closure rules here mirror ``graph_compiler_v3`` exactly
   (primary tree + ``global_context`` + edges that declare
   ``include_in_branch`` / ``include_subtree_in_branch`` / ``applies_to``), so
   the site and the agent scope knowledge the same way.

2. **Only registered relations.** A block may only walk a relation the graph
   already knows. This keeps the block vocabulary closed instead of letting
   templates grow into an ad-hoc query language.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Optional


# Relations a block may traverse. Mirrors knowledge_relation_type_registry; the
# registry stays the authority, this is the subset the site output uses.
ALLOWED_RELATIONS = {
    "contains",
    "about_product",
    "uses_asset",
    "gallery_asset",
    "visible_to_agent",
    "publishes_to",
    "applies_to",
}

# Edge metadata flags that let a non-primary edge widen a branch.
_BRANCH_FLAGS = ("include_in_branch", "include_subtree_in_branch")


def _data(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("data")
    return value if isinstance(value, dict) else {}


def _capability(node: dict[str, Any], name: str) -> bool:
    caps = _data(node).get("capabilities")
    return bool(caps.get(name)) if isinstance(caps, dict) else False


def is_branch_anchor(node: dict[str, Any]) -> bool:
    return _capability(node, "branch_anchor")


class SiteBlockError(RuntimeError):
    """Template asked for something the graph does not allow."""


# ── Branch closure ────────────────────────────────────────────────────────


def _primary_tree(edges: Iterable[dict[str, Any]]):
    children: dict[str, list[str]] = {}
    parents: dict[str, str] = {}
    for edge in edges:
        if edge.get("relation_type") != "contains":
            continue
        children.setdefault(edge["source"], []).append(edge["target"])
        parents[edge["target"]] = edge["source"]
    return children, parents


def _descendants(root: str, children: dict[str, list[str]]) -> set[str]:
    out: set[str] = set()
    queue = deque([root])
    while queue:
        current = queue.popleft()
        if current in out:
            continue
        out.add(current)
        queue.extend(children.get(current, []))
    return out


def branch_closure(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    anchor_id: str,
) -> set[str]:
    """Every node the given branch anchor may see.

    Same three sources as the compiler: the anchor's primary subtree plus its
    ancestors, every ``global_context`` subtree, and non-primary edges that
    explicitly opt into branch scope. An edge without one of those flags never
    widens the branch -- that is what stops two brands from bleeding into each
    other through a shared product.
    """
    if anchor_id not in nodes:
        raise SiteBlockError(f"scope_anchor_not_found:{anchor_id}")
    if not is_branch_anchor(nodes[anchor_id]):
        raise SiteBlockError(f"scope_is_not_branch_anchor:{anchor_id}")

    children, parents = _primary_tree(edges)

    ancestors: list[str] = []
    current = anchor_id
    seen = {current}
    while current in parents:
        current = parents[current]
        if current in seen:
            break
        seen.add(current)
        ancestors.append(current)

    members = _descendants(anchor_id, children) | set(ancestors)
    for node_id, node in nodes.items():
        if _capability(node, "global_context"):
            members |= _descendants(node_id, children)

    frontier = set(members)
    for edge in edges:
        relation = edge.get("relation_type")
        if relation == "contains":
            continue
        metadata = edge.get("metadata") or {}
        subtree = metadata.get("include_subtree_in_branch") is True
        opted_in = subtree or metadata.get("include_in_branch") is True
        if not opted_in and relation != "applies_to":
            continue

        def admit(node_id: str) -> None:
            members.update(
                _descendants(node_id, children) if subtree else {node_id}
            )

        if edge["source"] in frontier and edge["target"] not in members:
            admit(edge["target"])
        elif edge["target"] in frontier and edge["source"] not in members:
            admit(edge["source"])

    return members


# ── Template registry ─────────────────────────────────────────────────────
#
# Shape of a block:
#   node_type   which nodes seed the block
#   relations   named traversals used to enrich each seed
#   optional    a missing block is dropped instead of failing the build

TEMPLATES: dict[str, dict[str, Any]] = {
    "landing_page": {
        "requires": ["brand", "product_group", "offer"],
        "blocks": [
            {"id": "hero", "kind": "hero", "node_type": "brand"},
            {
                "id": "groups",
                "kind": "group_index",
                "node_type": "product_group",
                "relations": {
                    "products": "contains",
                    "offers": "about_product",
                    "assets": "contains",
                },
            },
            {"id": "brand", "kind": "brand", "node_type": "brand"},
            {"id": "price_range", "kind": "price_range", "node_type": "offer"},
            {"id": "faq", "kind": "faq", "node_type": "faq", "optional": True},
            {"id": "whatsapp_cta", "kind": "cta", "node_type": "brand"},
        ],
    },
}


def _check_relations(template: dict[str, Any]) -> None:
    for block in template["blocks"]:
        for name, relation in (block.get("relations") or {}).items():
            if relation not in ALLOWED_RELATIONS:
                raise SiteBlockError(
                    f"unregistered_relation:{block['id']}:{name}:{relation}"
                )


# ── Resolution helpers ────────────────────────────────────────────────────


def _money(amount: Any) -> Optional[int]:
    """Prices travel as integer cents so the renderer never does float math."""
    try:
        return int(round(float(amount) * 100))
    except (TypeError, ValueError):
        return None


def _offer_price_cents(offer: dict[str, Any]) -> Optional[int]:
    price = _data(offer).get("price")
    return _money(price.get("amount")) if isinstance(price, dict) else None


def _asset_payload(asset: dict[str, Any]) -> dict[str, Any]:
    media = _data(asset).get("media")
    media = media if isinstance(media, dict) else {}
    return {
        "node_id": asset["id"],
        "alt": asset.get("title") or "",
        # The publisher does not yet write assets.knowledge_node_id, so a bundle
        # asset has no resolvable public URL. Emitting bucket/path keeps the
        # binding visible without inventing a link the renderer cannot load.
        "bucket": media.get("bucket"),
        "path": media.get("path"),
        "url": media.get("url"),
    }


def _is_site_faq(node: dict[str, Any]) -> bool:
    """Only FAQs an operator explicitly elected for the site.

    Derived FAQs (generated from a copy or a product group) are conversation
    retrieval material: they read as agent script, restate structure the page
    already shows, and go stale the moment the catalog changes. Greeting and
    qualification FAQs carry a ``role`` and are conversation mechanics. Neither
    belongs on a public page, so a FAQ reaches the site only by opting in.
    """
    data = _data(node)
    if data.get("source_node_id") or data.get("role"):
        return False
    return data.get("site_faq") is True


# ── Block resolvers ───────────────────────────────────────────────────────


def _resolve_groups(
    block: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    scoped: set[str],
) -> list[dict[str, Any]]:
    group_products: dict[str, list[str]] = {}
    product_offers: dict[str, list[str]] = {}
    product_assets: dict[str, list[str]] = {}

    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source not in scoped or target not in scoped:
            continue
        source_type = nodes.get(source, {}).get("node_type")
        target_type = nodes.get(target, {}).get("node_type")
        relation = edge.get("relation_type")

        if relation == "contains" and source_type == "product_group" and target_type == "product":
            group_products.setdefault(source, []).append(target)
        elif relation == "about_product" and source_type == "offer" and target_type == "product":
            product_offers.setdefault(target, []).append(source)
        elif relation == "contains" and source_type == "product" and target_type == "asset":
            product_assets.setdefault(source, []).append(target)

    out: list[dict[str, Any]] = []
    for group_id, product_ids in group_products.items():
        group = nodes[group_id]
        prices = [
            price
            for product_id in product_ids
            for offer_id in product_offers.get(product_id, [])
            if (price := _offer_price_cents(nodes[offer_id])) is not None
        ]
        assets = [
            _asset_payload(nodes[asset_id])
            for product_id in product_ids
            for asset_id in product_assets.get(product_id, [])
        ]
        out.append({
            "node_id": group_id,
            "slug": group.get("slug"),
            "title": group.get("title"),
            "summary": _meaningful_summary(group),
            "product_count": len(product_ids),
            "price_from_cents": min(prices) if prices else None,
            # A group renders with or without a picture; the page must not
            # depend on media that may never be bound.
            "assets": assets,
        })
    out.sort(key=lambda row: -row["product_count"])
    return out


def _vocabulary(
    nodes: dict[str, dict[str, Any]], scoped: set[str]
) -> list[dict[str, Any]]:
    """How customers actually ask for things, grouped by audience.

    Context audiences carry the words real buyers use -- fabrics (poá, modal,
    tule), fit (G1-G4), motive (promoção). Keeping them grouped by their
    audience node preserves the graph's own structure instead of flattening
    everything into one undifferentiated word cloud, and it stays generic: any
    persona with context audiences gets the same treatment.
    """
    groups: list[dict[str, Any]] = []
    for node_id in sorted(scoped):
        node = nodes.get(node_id) or {}
        if node.get("node_type") != "audience" or is_branch_anchor(node):
            continue
        terms = [str(alias).strip() for alias in _data(node).get("aliases") or []]
        terms = [term for term in terms if term]
        if not terms:
            continue
        groups.append({
            "node_id": node_id,
            "label": node.get("title"),
            "terms": terms,
        })
    return groups


def _meaningful_summary(node: dict[str, Any]) -> Optional[str]:
    """Drop summaries that only restate the title.

    Bulk-generated nodes carry filler like "Grupo de produtos: vestidos." for
    the group titled "Vestidos". Rendering that adds a line of noise under
    every row, so the page is better off with nothing.
    """
    summary = (node.get("summary") or "").strip()
    title = (node.get("title") or "").strip()
    if not summary or not title:
        return summary or None
    normalized = summary.rstrip(".").lower()
    if normalized.endswith(title.lower()) and len(summary) <= len(title) + 24:
        return None
    return summary


def resolve_blocks(
    bundle: dict[str, Any],
    *,
    template_key: str,
    scope: str,
    site: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a public page payload from a graph bundle.

    ``scope`` is a branch anchor node id. Nothing outside that branch's closure
    can appear in the result.
    """
    template = TEMPLATES.get(template_key)
    if template is None:
        raise SiteBlockError(f"unknown_template:{template_key}")
    _check_relations(template)

    nodes = {node["id"]: node for node in bundle["nodes"]}
    edges = bundle["edges"]
    scoped = branch_closure(nodes, edges, scope)

    def in_scope(node_type: str) -> list[dict[str, Any]]:
        return [
            nodes[node_id]
            for node_id in scoped
            if node_id in nodes and nodes[node_id].get("node_type") == node_type
        ]

    missing = [
        node_type for node_type in template["requires"] if not in_scope(node_type)
    ]
    if missing:
        raise SiteBlockError(f"template_requires_missing:{','.join(missing)}")

    brands = in_scope("brand")
    if len(brands) != 1:
        # More than one brand in a single branch means the scope is not really
        # isolating a commercial identity, and the page would have to guess.
        raise SiteBlockError(
            f"expected_exactly_one_brand_in_scope:{[b['id'] for b in brands]}"
        )
    brand = brands[0]
    brand_data = _data(brand)

    prices = [
        price
        for offer in in_scope("offer")
        if (price := _offer_price_cents(offer)) is not None
    ]

    blocks: list[dict[str, Any]] = []
    for spec in template["blocks"]:
        kind = spec["kind"]
        payload: dict[str, Any]

        if kind == "hero":
            payload = {
                "brand_node_id": brand["id"],
                "title": brand.get("title"),
                "positioning": brand_data.get("positioning"),
                "vocabulary": _vocabulary(nodes, scoped),
            }
        elif kind == "brand":
            payload = {
                "node_id": brand["id"],
                "title": brand.get("title"),
                "summary": brand.get("summary"),
                "positioning": brand_data.get("positioning"),
                "personality": brand_data.get("personality") or [],
                "audience_fit": brand_data.get("audience_fit"),
                "pricing_model": brand_data.get("pricing_model"),
            }
        elif kind == "group_index":
            payload = {"groups": _resolve_groups(spec, nodes, edges, scoped)}
        elif kind == "price_range":
            payload = {
                "min_cents": min(prices) if prices else None,
                "max_cents": max(prices) if prices else None,
                "offer_count": len(prices),
            }
        elif kind == "faq":
            payload = {
                "items": [
                    {
                        "node_id": node["id"],
                        "question": _data(node).get("question") or node.get("title"),
                        "answer": _data(node).get("answer") or node.get("summary"),
                    }
                    for node in in_scope("faq")
                    if _is_site_faq(node)
                ]
            }
        elif kind == "cta":
            payload = {
                "headline": brand_data.get("cta"),
                "phone": (site or {}).get("whatsapp_phone"),
                "message_template": (site or {}).get("whatsapp_message_template"),
            }
        else:
            raise SiteBlockError(f"unknown_block_kind:{kind}")

        empty = not any(payload.get(key) for key in payload)
        if empty and spec.get("optional"):
            continue
        blocks.append({"id": spec["id"], "kind": kind, "data": payload})

    return {
        "template": template_key,
        "scope": scope,
        "persona_slug": bundle["persona"]["slug"],
        "site": site or {},
        "blocks": blocks,
    }
