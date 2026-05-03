# -*- coding: utf-8 -*-
"""
knowledge_graph: lightweight semantic graph layer over knowledge_items / kb_entries.

Responsibilities:
- Keep a normalized graph of personas, products, campaigns, faqs, copies,
  assets, rules, etc. via knowledge_nodes + knowledge_edges (migration 008).
- Bootstrap nodes/edges from synced vault items so the existing flow
  (vault → knowledge_items → kb_entries) continues to work unchanged.
- Resolve a "chat context": given a lead's recent messages, find related
  products/campaigns/assets via term matching + 1-hop neighbourhood.

All public functions are defensive: if migration 008 is not yet applied or
any DB error occurs, they degrade to empty lists rather than raising. The
old text-based KB search keeps working as the fallback.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable, Optional

from services import supabase_client

logger = logging.getLogger("knowledge_graph")

# The graph layer must not ship client/product-specific canonical data.
# Product, campaign, brand and entity nodes are inferred from the current
# knowledge item metadata/frontmatter and from nodes that already exist.
_TOPIC_NODE_TYPES = {"product", "campaign", "brand", "entity", "persona", "audience"}

# Map content_type → node_type for items mirrored into the graph.
_CONTENT_TYPE_TO_NODE: dict[str, str] = {
    "faq":      "faq",
    "copy":     "copy",
    "campaign": "campaign",
    "product":  "product",
    "asset":    "asset",
    "rule":     "rule",
    "tone":     "tone",
    "audience": "audience",
    "entity":   "entity",
    "brand":    "brand",
    "briefing": "briefing",
    "prompt":   "rule",
    "competitor": "audience",
}

# Roles allowed in agent_visibility. Used for `visible_to_agent` edges.
_KNOWN_ROLES = {"sdr", "closer", "followup", "maker", "classifier"}

_VALIDATED_ITEM_STATUSES = {"approved", "embedded", "ativo", "active", "validated"}
_PENDING_ITEM_STATUSES = {"pending", "needs_persona", "needs_category", "draft"}


# ── Helpers ───────────────────────────────────────────────────────────────

def _slugify(value: str) -> str:
    s = (value or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "item"


def _fold(value: str) -> str:
    """Lowercase text and remove accents for cheap Portuguese matching."""
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower()


def _normalize_tags(tags) -> list[str]:
    """Accept tags as text[] OR jsonb (string list, comma-separated string,
    or single string). Always returns a list[str] in lowercase."""
    if not tags:
        return []
    if isinstance(tags, str):
        # comma-separated, possibly JSON-encoded
        try:
            import json as _json
            parsed = _json.loads(tags)
            if isinstance(parsed, list):
                return [str(t).strip().lower() for t in parsed if t]
        except Exception:
            pass
        return [t.strip().lower() for t in tags.split(",") if t.strip()]
    if isinstance(tags, list):
        return [str(t).strip().lower() for t in tags if t]
    return []


def _source_status(item: dict, source_table: str) -> str:
    if source_table == "kb_entries":
        return str(item.get("status") or "ATIVO")
    return str(item.get("status") or "pending")


def _is_validated_source(source_table: Optional[str], status: Optional[str], node_type: Optional[str] = None) -> bool:
    status_l = str(status or "").lower()
    if source_table == "knowledge_items":
        return status_l in {"approved", "embedded"}
    if source_table == "kb_entries":
        return status_l in {"ativo", "active", "validated"}
    if node_type in {"product", "campaign", "persona"} and status_l in {"active", "validated", ""}:
        return True
    return status_l in _VALIDATED_ITEM_STATUSES


def _validation_state(node: dict) -> str:
    meta = node.get("metadata") or {}
    source_table = node.get("source_table")
    status = meta.get("source_status") or node.get("status")
    return "validated" if _is_validated_source(source_table, status, node.get("node_type")) else "pending"


def _link_target(node: dict) -> str:
    meta = node.get("metadata") or {}
    source_table = node.get("source_table")
    source_id = node.get("source_id")
    node_type = node.get("node_type") or "node"
    slug = node.get("slug") or node.get("id")
    if node_type == "asset" and meta.get("file_path"):
        return f"/api-brain/knowledge/file?path={meta['file_path']}"
    if source_table == "knowledge_items" and source_id:
        return f"/knowledge/quality?item_id={source_id}"
    if source_table == "kb_entries" and source_id:
        return f"/knowledge/graph?focus={node_type}:{slug}&kb_entry_id={source_id}"
    return f"/knowledge/graph?focus={node_type}:{slug}"


def _decorate_node(node: dict) -> dict:
    state = _validation_state(node)
    out = dict(node)
    out["validation_status"] = state
    out["validated"] = state == "validated"
    out["link_target"] = _link_target(node)
    return out


def _tipo_to_node_type(tipo: str) -> str:
    t = (tipo or "").lower()
    return {
        "produto": "product",
        "product": "product",
        "faq": "faq",
        "copy": "copy",
        "briefing": "briefing",
        "campanha": "campaign",
        "campaign": "campaign",
        "asset": "asset",
        "tom": "tone",
        "tone": "tone",
        "regra": "rule",
        "rule": "rule",
        "marca": "brand",
        "brand": "brand",
        "entidade": "entity",
        "entity": "entity",
    }.get(t, "knowledge_item")


def _common_prefix_len(a: str, b: str) -> int:
    """Return the length of the longest common prefix of a and b."""
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _prefix_overlap(needle: str, haystack_tokens: set[str], min_prefix: int = 4) -> bool:
    """True when `needle` shares a prefix of at least min_prefix chars with
    any token in haystack_tokens. Useful for Portuguese plural/singular
    pairs like modal/modais, papel/papeis, animal/animais."""
    if len(needle) < min_prefix:
        return False
    for tok in haystack_tokens:
        if len(tok) < min_prefix:
            continue
        if _common_prefix_len(needle, tok) >= min_prefix:
            return True
    return False


def _term_matches(terms: list[str], *values: object) -> bool:
    """True when any detected term appears in the given title/content/tags."""
    if not terms:
        return False
    blob = _fold(" ".join(str(v or "") for v in values))
    if not blob:
        return False
    for term in terms:
        folded = _fold(str(term))
        if not folded:
            continue
        slug_term = folded.replace(" ", "-")
        if folded in blob or slug_term in blob:
            return True
    return False


def _title_from_slug(slug: str) -> str:
    return (slug or "").replace("-", " ").replace("_", " ").title()


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _structured_metadata(fm: dict) -> dict:
    """Metadata fields that should survive into graph nodes.

    Keep this generic: scenario/product-specific values live in the incoming
    metadata, not in code.
    """
    if not isinstance(fm, dict):
        return {}
    out: dict = {}
    nested = fm.get("metadata")
    if isinstance(nested, dict):
        out.update(nested)
    for key in (
        "aliases",
        "synonyms",
        "price",
        "colors_count",
        "size",
        "catalog_url",
        "brand",
        "campaign",
        "campaigns",
        "product",
        "products",
    ):
        if key in fm and fm.get(key) is not None:
            out[key] = fm.get(key)
    return out


def _fallback_nodes_from_tables(terms: list[str], persona_id: Optional[str], existing_source_ids: set[str]) -> list[dict]:
    """Surface matching legacy knowledge_items/kb_entries even before graph sync."""
    if not terms:
        return []

    out: list[dict] = []
    try:
        items = supabase_client.get_knowledge_items(persona_id=persona_id, limit=300, offset=0)
    except Exception:
        items = []
    for item in items or []:
        sid = str(item.get("id") or "")
        if not sid or sid in existing_source_ids:
            continue
        content = item.get("content") or ""
        item_tags = _normalize_tags(item.get("tags"))
        if not _term_matches(terms, item.get("title"), content, item.get("file_path"), " ".join(item_tags)):
            continue
        content_type = (item.get("content_type") or "knowledge_item").lower()
        out.append(_decorate_node({
            "id": f"ki:{sid}",
            "persona_id": item.get("persona_id"),
            "source_table": "knowledge_items",
            "source_id": item.get("id"),
            "node_type": _CONTENT_TYPE_TO_NODE.get(content_type, content_type),
            "slug": _slugify(item.get("file_path") or item.get("title") or sid)[:80],
            "title": item.get("title") or content_type,
            "summary": content[:400],
            "tags": item_tags or [_slugify(terms[0])],
            "metadata": {
                "file_path": item.get("file_path"),
                "source_status": item.get("status") or "pending",
                "fallback": True,
            },
            "status": "validated" if _is_validated_source("knowledge_items", item.get("status"), content_type) else "pending",
        }))

    try:
        entries = supabase_client.get_kb_entries(persona_id=persona_id, status="ATIVO")
    except Exception:
        entries = []
    for entry in entries or []:
        sid = str(entry.get("id") or "")
        if not sid or sid in existing_source_ids:
            continue
        content = entry.get("conteudo") or ""
        entry_tags = _normalize_tags(entry.get("tags"))
        if not _term_matches(terms, entry.get("titulo"), content, entry.get("produto"), " ".join(entry_tags)):
            continue
        node_type = _tipo_to_node_type(entry.get("tipo") or entry.get("categoria") or "")
        out.append(_decorate_node({
            "id": f"kb:{sid}",
            "persona_id": entry.get("persona_id"),
            "source_table": "kb_entries",
            "source_id": entry.get("id"),
            "node_type": node_type,
            "slug": _slugify(entry.get("titulo") or sid)[:80],
            "title": entry.get("titulo") or node_type,
            "summary": content[:400],
            "tags": entry_tags or [_slugify(terms[0])],
            "metadata": {
                "source_status": entry.get("status") or "ATIVO",
                "fallback": True,
            },
            "status": "validated",
        }))
    return out


def _persona_id_from_slug(persona_slug_or_id: Optional[str]) -> Optional[str]:
    """Resolve a persona slug or UUID into a UUID, or return None."""
    if not persona_slug_or_id:
        return None
    if len(persona_slug_or_id) == 36 and persona_slug_or_id.count("-") == 4:
        return persona_slug_or_id
    p = supabase_client.get_persona(persona_slug_or_id)
    return p.get("id") if p else None


# ── Canonical nodes (idempotent) ──────────────────────────────────────────

def ensure_canonical_for_persona(persona_id: Optional[str]) -> dict:
    """Legacy no-op.

    Canonical graph nodes are now derived from real knowledge metadata instead
    of being shipped with client/product-specific defaults.
    """
    return {}


def rebuild_graph_for_persona(
    persona_id: Optional[str],
    limit_items: int = 1000,
    limit_kb: int = 1000,
) -> dict:
    """Re-run bootstrap_from_item for every existing knowledge_items + kb_entries
    row tied to a persona (or globally when persona_id is None).

    Idempotent — existing nodes/edges are preserved by the upsert keys, and
    bootstrap is fully driven by the source data (no client-specific seeds).

    Used after migration 008 is applied or whenever the graph drifts from
    the source-of-truth tables.

    Returns a counts dict with mirror/skip totals + first 20 errors.
    """
    counts: dict = {
        "items_seen": 0, "items_mirrored": 0, "items_skipped": 0,
        "kb_seen": 0, "kb_mirrored": 0, "kb_skipped": 0,
        "errors": [],
    }

    try:
        items = supabase_client.get_knowledge_items(
            persona_id=persona_id, limit=limit_items, offset=0,
        ) or []
    except Exception as exc:
        counts["errors"].append(f"get_knowledge_items: {exc}")
        items = []

    for item in items:
        counts["items_seen"] += 1
        try:
            mirror = bootstrap_from_item(
                item,
                frontmatter=item.get("metadata") or {},
                body=item.get("content") or "",
                persona_id=item.get("persona_id") or persona_id,
                source_table="knowledge_items",
            )
            if mirror:
                counts["items_mirrored"] += 1
            else:
                counts["items_skipped"] += 1
        except Exception as exc:
            counts["items_skipped"] += 1
            counts["errors"].append(f"item {item.get('id')}: {str(exc)[:120]}")

    try:
        entries = supabase_client.get_kb_entries(persona_id=persona_id, status="") or []
    except Exception as exc:
        counts["errors"].append(f"get_kb_entries: {exc}")
        entries = []

    for entry in entries[:limit_kb]:
        counts["kb_seen"] += 1
        try:
            mirror = bootstrap_from_item(
                {
                    "id": entry.get("id"),
                    "title": entry.get("titulo"),
                    "content_type": entry.get("categoria") or entry.get("tipo") or "faq",
                    "content": entry.get("conteudo") or "",
                    "tags": entry.get("tags") or [],
                    "status": entry.get("status") or "ATIVO",
                    "persona_id": entry.get("persona_id"),
                    "file_path": entry.get("link"),
                    "kb_id": entry.get("kb_id"),
                },
                frontmatter={},
                body=entry.get("conteudo") or "",
                persona_id=entry.get("persona_id") or persona_id,
                source_table="kb_entries",
            )
            if mirror:
                counts["kb_mirrored"] += 1
            else:
                counts["kb_skipped"] += 1
        except Exception as exc:
            counts["kb_skipped"] += 1
            counts["errors"].append(f"kb {entry.get('id')}: {str(exc)[:120]}")

    counts["errors"] = counts["errors"][:20]
    return counts


# ── Bootstrap from a synced item ──────────────────────────────────────────

def _gather_blob(item: dict, frontmatter: dict, body: str) -> str:
    """Concatenate every field that may carry product/campaign hints."""
    parts: list[str] = []
    for field in ("title", "file_path", "content_type"):
        v = item.get(field) or ""
        parts.append(str(v))
    for v in _normalize_tags(item.get("tags")):
        parts.append(v)
    for k in ("product", "campaign", "campaigns", "title", "tags", "type", "aliases", "synonyms"):
        v = frontmatter.get(k)
        if isinstance(v, list):
            parts.extend([str(x) for x in v])
        elif v is not None:
            parts.append(str(v))
    if body:
        parts.append(body[:2000])
    return " ".join(parts)


def _explicit_relations_from_frontmatter(fm: dict) -> list[tuple[str, str]]:
    """Read graph.relates_to from frontmatter as [type:slug] strings.

    Returns list of (node_type, slug) tuples."""
    rel = []
    g = fm.get("graph") or {}
    if isinstance(g, dict):
        items = g.get("relates_to") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, str) or ":" not in it:
                    continue
                ntype, slug = it.split(":", 1)
                if ntype.strip() and slug.strip():
                    rel.append((ntype.strip().lower(), _slugify(slug)))
    # Also accept common shorthand frontmatter.
    relation_fields = {
        "campaign": "campaign",
        "campaigns": "campaign",
        "product": "product",
        "products": "product",
        "brand": "brand",
        "brands": "brand",
        "entity": "entity",
        "entities": "entity",
        "persona": "persona",
        "personas": "persona",
        "audience": "audience",
        "audiences": "audience",
    }
    for key, ntype in relation_fields.items():
        for value in _as_list(fm.get(key)):
            if value:
                rel.append((ntype, _slugify(str(value))))

    # Tags like product:<slug> or campaign:<slug> are also explicit graph hints.
    for tag in _normalize_tags(fm.get("tags")):
        if ":" not in tag:
            continue
        ntype, slug = tag.split(":", 1)
        ntype = ntype.strip().lower()
        if ntype in _TOPIC_NODE_TYPES and slug.strip():
            rel.append((ntype, _slugify(slug)))

    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ntype, slug in rel:
        key = (ntype, slug)
        if slug and key not in seen:
            seen.add(key)
            dedup.append(key)
    return dedup


def _topic_relations_for_item(item: dict, fm: dict, node_type: str) -> list[tuple[str, str]]:
    """Infer topic nodes from explicit metadata and the item's own type."""
    rel = list(_explicit_relations_from_frontmatter(fm))

    title = item.get("title") or item.get("titulo") or ""
    if node_type in _TOPIC_NODE_TYPES and title:
        rel.append((node_type, _slugify(str(fm.get("slug") or fm.get(node_type) or title))))

    for tag in _normalize_tags(item.get("tags")):
        if ":" not in tag:
            continue
        ntype, slug = tag.split(":", 1)
        if ntype in _TOPIC_NODE_TYPES and slug:
            rel.append((ntype, _slugify(slug)))

    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ntype, slug in rel:
        key = (ntype, slug)
        if slug and key not in seen:
            seen.add(key)
            dedup.append(key)
    return dedup


def _relation_title(ntype: str, slug: str, item: dict, fm: dict) -> str:
    explicit_title = fm.get(f"{ntype}_title") or fm.get(f"{ntype}_name")
    if explicit_title:
        for key in (ntype, f"{ntype}s"):
            if any(value and _slugify(str(value)) == slug for value in _as_list(fm.get(key))):
                return str(explicit_title).replace("_", " ").strip()
    for key in (ntype, f"{ntype}s"):
        for value in _as_list(fm.get(key)):
            if value and _slugify(str(value)) == slug:
                return str(value).replace("_", " ").strip().title()
    if _CONTENT_TYPE_TO_NODE.get((item.get("content_type") or "").lower()) == ntype:
        title = item.get("title") or item.get("titulo")
        if title:
            return str(title)
    return _title_from_slug(slug)


def _extract_faq_pairs(text: str) -> list[tuple[str, str]]:
    """Extract Pergunta:/Resposta: blocks from vault, manual items, or KB text."""
    if not text:
        return []
    pattern = re.compile(
        r"Pergunta:\s*(?P<q>.*?)\s*Resposta:\s*(?P<a>.*?)(?=\n\s*Pergunta:|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    pairs: list[tuple[str, str]] = []
    for match in pattern.finditer(text):
        q = re.sub(r"\s+", " ", match.group("q")).strip()
        a = re.sub(r"\s+", " ", match.group("a")).strip()
        if q and a:
            pairs.append((q, a))
    return pairs


def _faq_slug(question: str, topic_slug: Optional[str] = None) -> str:
    base = _slugify(question)[:70].strip("-")
    if topic_slug and base and not base.startswith(f"{topic_slug}-"):
        return f"{topic_slug}-{base}"[:80].strip("-")
    return base[:80] or "faq"


def _extract_briefing_sections(title: str, text: str) -> list[tuple[str, str, str]]:
    """Return (slug, heading, summary) for markdown briefing sections."""
    out: list[tuple[str, str, str]] = []
    if title:
        out.append((_slugify(title), title, (text or "")[:500]))

    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading = stripped.lstrip("#").strip()
        if not heading:
            continue
        slug = _slugify(heading)
        snippet = "\n".join(lines[i + 1:i + 6]).strip()[:500]
        out.append((slug, heading, snippet))

    dedup: dict[str, tuple[str, str, str]] = {}
    for row in out:
        dedup[row[0]] = row
    return list(dedup.values())


def _bootstrap_derived_subnodes(
    mirror: dict,
    item: dict,
    frontmatter: dict,
    body: str,
    persona_id: Optional[str],
    topic_nodes: list[dict],
    source_table: str,
) -> None:
    """Create FAQ, briefing and mention subnodes for any related topic."""
    if not mirror or not topic_nodes:
        return

    title = item.get("title") or item.get("titulo") or mirror.get("title") or ""
    tags = _normalize_tags(item.get("tags")) + _normalize_tags(frontmatter.get("tags"))
    content = body or item.get("content") or item.get("conteudo") or ""
    content_type = (item.get("content_type") or item.get("tipo") or "").lower()
    primary_topic = next((n for n in topic_nodes if n.get("node_type") == "product"), topic_nodes[0])
    topic_slug = primary_topic.get("slug") or _slugify(primary_topic.get("title") or "topic")
    topic_tags = {topic_slug, *(n.get("slug") for n in topic_nodes if n.get("slug")), *tags}

    status = _source_status(item, source_table)
    validated = _is_validated_source(source_table, status, mirror.get("node_type"))
    base_meta = {
        "source_status": status,
        "parent_node_id": mirror.get("id"),
        "parent_title": mirror.get("title"),
        "file_path": item.get("file_path"),
    }

    for topic in topic_nodes:
        rel = "about_product" if topic.get("node_type") == "product" else "same_topic_as"
        if topic.get("node_type") == "campaign":
            rel = "part_of_campaign"
        supabase_client.upsert_knowledge_edge(
            topic["id"], mirror["id"], rel, persona_id=persona_id,
        )

    for question, answer in _extract_faq_pairs(content):
        faq = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "source_table": source_table,
            "source_id": item.get("id"),
            "node_type": "faq",
            "slug": _faq_slug(question, topic_slug),
            "title": question,
            "summary": answer[:500],
            "tags": sorted({"faq", *topic_tags}),
            "status": "validated" if validated else "pending",
            "metadata": {
                **base_meta,
                "derived_from": "faq_block",
                "question": question,
                "answer": answer,
            },
        })
        if faq:
            for topic in topic_nodes:
                supabase_client.upsert_knowledge_edge(
                    topic["id"], faq["id"], "answers_question", persona_id=persona_id,
                )
            supabase_client.upsert_knowledge_edge(
                mirror["id"], faq["id"], "contains", persona_id=persona_id,
            )
            supabase_client.upsert_knowledge_edge(
                faq["id"], mirror["id"], "derived_from", persona_id=persona_id,
            )

    is_briefing = content_type == "briefing" or "briefing" in _fold(str(item.get("file_path") or ""))
    if is_briefing:
        for slug, heading, snippet in _extract_briefing_sections(title, content):
            briefing = supabase_client.upsert_knowledge_node({
                "persona_id": persona_id,
                "source_table": source_table,
                "source_id": item.get("id"),
                "node_type": "briefing",
                "slug": slug,
                "title": heading,
                "summary": snippet,
                "tags": sorted({"briefing", *topic_tags}),
                "status": "validated" if validated else "pending",
                "metadata": {**base_meta, "derived_from": "briefing_heading"},
            })
            if briefing:
                for topic in topic_nodes:
                    supabase_client.upsert_knowledge_edge(
                        topic["id"], briefing["id"], "briefed_by", persona_id=persona_id,
                    )
                supabase_client.upsert_knowledge_edge(
                    mirror["id"], briefing["id"], "contains", persona_id=persona_id,
                )

    # General files related to a topic still get a small mention node. This
    # makes broad brand/tone/audience files visible without treating them as FAQ.
    if content_type not in {"faq", "product", "asset", "copy", "campaign", "briefing"}:
        mention = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "source_table": source_table,
            "source_id": item.get("id"),
            "node_type": "mention",
            "slug": f"{topic_slug}-{mirror.get('slug')}"[:80].strip("-"),
            "title": f"{primary_topic.get('title') or _title_from_slug(topic_slug)} - {title}",
            "summary": (content or mirror.get("summary") or "")[:300],
            "tags": sorted({"mention", *topic_tags}),
            "status": "validated" if validated else "pending",
            "metadata": {**base_meta, "derived_from": "topic_mention"},
        })
        if mention:
            for topic in topic_nodes:
                supabase_client.upsert_knowledge_edge(
                    topic["id"], mention["id"], "mentions", persona_id=persona_id,
                )
            supabase_client.upsert_knowledge_edge(
                mention["id"], mirror["id"], "derived_from", persona_id=persona_id,
            )


def bootstrap_from_item(
    item: dict,
    frontmatter: Optional[dict] = None,
    body: str = "",
    persona_id: Optional[str] = None,
    source_table: str = "knowledge_items",
) -> Optional[dict]:
    """Create/refresh the graph nodes & edges that mirror this synced item.

    Always-on heuristics:
      - mirror the item itself as a node (`knowledge_item` or content_type-mapped node).
      - persona membership via belongs_to_persona.
      - explicit product/campaign/brand/entity relations from frontmatter/tags.
      - asset items also get `supports_campaign` / `uses_asset` edges.

    Returns the mirror node (or None when migration 008 isn't applied yet).
    """
    if not item:
        return None
    fm = frontmatter or {}
    persona_id = persona_id or item.get("persona_id")

    try:
        # 1) Mirror node for the item itself.
        content_type = (item.get("content_type") or "").lower()
        node_type = _CONTENT_TYPE_TO_NODE.get(content_type, source_table.rstrip("s"))
        # node_type fallback: "knowledge_items" → "knowledge_item", "kb_entries" → "kb_entrie"
        if node_type == "knowledge_item" or node_type == "kb_entrie":
            node_type = "knowledge_item" if source_table == "knowledge_items" else "kb_entry"

        slug_seed = fm.get("slug") or item.get("file_path") or item.get("title") or str(item.get("id") or "")
        slug = _slugify(slug_seed)[:80] or _slugify(str(item.get("id") or "x"))
        title = item.get("title") or item.get("titulo") or slug
        tags = _normalize_tags(item.get("tags"))
        source_status = _source_status(item, source_table)

        meta: dict = {
            "content_type": content_type or None,
            "file_path": item.get("file_path"),
            "file_type": item.get("file_type"),
            "asset_type": item.get("asset_type") or fm.get("asset_type"),
            "asset_function": item.get("asset_function") or fm.get("asset_function"),
            "kb_id": item.get("kb_id"),
            "source_status": source_status,
        }
        meta.update(_structured_metadata(fm))
        meta = {k: v for k, v in meta.items() if v is not None}

        mirror = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "source_table": source_table,
            "source_id": item.get("id"),
            "node_type": node_type,
            "slug": slug,
            "title": title,
            "summary": (item.get("content") or item.get("conteudo") or "")[:400] or None,
            "tags": tags,
            "metadata": meta,
            "status": "validated" if _is_validated_source(source_table, source_status, node_type) else "pending",
        })
        if not mirror:
            return None  # graph tables missing — silently skip, sync still works

        # 2) Persona link.
        if persona_id:
            persona_node = supabase_client.upsert_knowledge_node({
                "persona_id": persona_id,
                "node_type": "persona",
                "slug": "self",
                "title": "Persona",
                "metadata": {"role": "root"},
            })
            if persona_node:
                supabase_client.upsert_knowledge_edge(
                    mirror["id"], persona_node["id"], "belongs_to_persona", persona_id=persona_id,
                )

        # 3) Tag nodes + has_tag edges.
        for tag in tags:
            tnode = supabase_client.upsert_knowledge_node({
                "persona_id": persona_id,
                "node_type": "tag",
                "slug": _slugify(tag),
                "title": tag,
            })
            if tnode:
                supabase_client.upsert_knowledge_edge(
                    mirror["id"], tnode["id"], "has_tag", persona_id=persona_id,
                )

        # 4) Explicit topic relations from frontmatter/tags plus the item's own
        # type when it is itself a product/campaign/brand/entity.
        related: list[tuple[str, str]] = _topic_relations_for_item(item, fm, node_type)

        # 6) For each related (type, slug), upsert node + connect with the right edge.
        # Relation choice depends on the source item's content_type:
        #   asset  → product=uses_asset (inverted), campaign=supports_campaign
        #   faq    → product/campaign = answers_question
        #   copy   → product/campaign = supports_copy
        #   other  → product=about_product, campaign=part_of_campaign
        related_nodes: dict[tuple[str, str], dict] = {}
        for ntype, rslug in related:
            related_title = _relation_title(ntype, rslug, item, fm)
            target_meta = {"auto": True}
            if ntype == node_type and rslug == slug:
                target_meta.update(meta)
            target = supabase_client.upsert_knowledge_node({
                "persona_id": persona_id,
                "node_type": ntype,
                "slug": rslug,
                "title": related_title,
                "tags": [rslug],
                "metadata": target_meta,
            })
            if not target:
                continue
            related_nodes[(ntype, rslug)] = target

            # Default relation for non-special content types.
            relation = "about_product" if ntype == "product" else (
                "part_of_campaign" if ntype == "campaign" else "same_topic_as"
            )

            if content_type == "asset":
                if ntype == "campaign":
                    relation = "supports_campaign"
                elif ntype == "product":
                    # campaign/product → asset
                    supabase_client.upsert_knowledge_edge(
                        target["id"], mirror["id"], "uses_asset", persona_id=persona_id,
                    )
                    continue
            elif content_type == "faq" and ntype in ("product", "campaign"):
                relation = "answers_question"
            elif content_type == "copy" and ntype in ("product", "campaign"):
                relation = "supports_copy"

            supabase_client.upsert_knowledge_edge(
                mirror["id"], target["id"], relation, persona_id=persona_id,
            )
            if ntype == "product":
                supabase_client.upsert_knowledge_edge(
                    target["id"], mirror["id"], "about_product", persona_id=persona_id,
                )

        # 6) Product/campaign pairs from the same item are connected generically.
        products = [n for (ntype, _), n in related_nodes.items() if ntype == "product"]
        campaigns = [n for (ntype, _), n in related_nodes.items() if ntype == "campaign"]
        for product in products:
            for campaign in campaigns:
                supabase_client.upsert_knowledge_edge(
                    product["id"], campaign["id"], "part_of_campaign", persona_id=persona_id,
                )

        # 7) Derived subnodes for FAQ blocks, briefing headings and broad mentions.
        _bootstrap_derived_subnodes(
            mirror=mirror,
            item=item,
            frontmatter=fm,
            body=body,
            persona_id=persona_id,
            topic_nodes=[n for n in related_nodes.values() if n.get("node_type") in _TOPIC_NODE_TYPES],
            source_table=source_table,
        )

        # 8) Agent visibility from frontmatter.
        viz = fm.get("agent_visibility") or item.get("agent_visibility") or []
        if isinstance(viz, list):
            for role in viz:
                role_slug = _slugify(str(role))
                if not role_slug or role_slug not in _KNOWN_ROLES:
                    continue
                rnode = supabase_client.upsert_knowledge_node({
                    "persona_id": persona_id,
                    "node_type": "audience",   # role buckets live alongside audiences
                    "slug": f"role-{role_slug}",
                    "title": role_slug.upper(),
                    "metadata": {"role": role_slug},
                })
                if rnode:
                    supabase_client.upsert_knowledge_edge(
                        mirror["id"], rnode["id"], "visible_to_agent", persona_id=persona_id,
                    )

        return mirror
    except Exception as exc:
        # Never let graph maintenance abort vault sync or item promotion.
        logger.warning("bootstrap_from_item failed (item=%s): %s", item.get("id"), exc)
        return None


# ── Chat context resolver ─────────────────────────────────────────────────

def _compute_graph_distances(
    seed_ids: set[str],
    nodes: list[dict],
    edges: list[dict],
    max_distance: int = 4,
) -> tuple[dict[str, int], dict[str, list[dict]]]:
    """BFS over knowledge_edges to label each node with graph_distance and the
    path used to reach it from the nearest seed.

    Returns:
      (distance, path) where:
        distance[node_id] -> int  (0 for seeds, +1 per hop; absent => unreached)
        path[node_id]     -> list[{"node_id","slug","title","relation_type"|None}]
                             (always starts at a seed and ends at node_id)
    """
    if not seed_ids or not nodes:
        return {}, {}

    node_index: dict[str, dict] = {n["id"]: n for n in nodes if n.get("id")}
    # Adjacency: for each node, list of (neighbor_id, relation_type, direction)
    # Edges are directional in the schema; for path reconstruction we walk
    # both directions, but tag the relation correctly so callers can render
    # "A --rel--> B" or "A <--rel-- B".
    adj: dict[str, list[tuple[str, str, str]]] = {}
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        rel = e.get("relation_type") or "related"
        if not src or not tgt:
            continue
        adj.setdefault(src, []).append((tgt, rel, "out"))
        adj.setdefault(tgt, []).append((src, rel, "in"))

    distance: dict[str, int] = {}
    predecessor: dict[str, tuple[str, str, str]] = {}  # nid -> (parent_id, rel, direction)
    queue: list[tuple[str, int]] = []

    for sid in seed_ids:
        if sid in node_index:
            distance[sid] = 0
            queue.append((sid, 0))

    head = 0
    while head < len(queue):
        nid, d = queue[head]
        head += 1
        if d >= max_distance:
            continue
        for (nb, rel, direction) in adj.get(nid, []):
            if nb in distance or nb not in node_index:
                continue
            distance[nb] = d + 1
            predecessor[nb] = (nid, rel, direction)
            queue.append((nb, d + 1))

    def _path_for(nid: str) -> list[dict]:
        chain: list[dict] = []
        cur = nid
        guard = 0
        while cur is not None and guard < max_distance + 2:
            n = node_index.get(cur, {})
            entry: dict = {
                "node_id": cur,
                "slug": n.get("slug"),
                "title": n.get("title"),
                "node_type": n.get("node_type"),
                "relation_type": None,
                "direction": None,
            }
            if cur in predecessor:
                _, rel, direction = predecessor[cur]
                entry["relation_type"] = rel
                entry["direction"] = direction
            chain.append(entry)
            cur = predecessor.get(cur, (None,))[0] if cur in predecessor else None
            guard += 1
        chain.reverse()
        return chain

    paths: dict[str, list[dict]] = {nid: _path_for(nid) for nid in distance}
    return distance, paths


def _candidate_terms_from_messages(messages: Iterable[dict], horizon_chars: int = 2000) -> list[str]:
    """Pull the most recent words/phrases from a conversation that look like
    proper nouns or quoted product names. We're intentionally simple here —
    actual matching is gated by the canonical product/campaign list anyway."""
    blob = " ".join(((m or {}).get("texto") or "") for m in messages)[-horizon_chars:]
    if not blob:
        return []
    # Words >= 3 chars, lowercase, deduped, preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'-]{2,}", blob):
        t = token.lower()
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _detect_terms(
    user_text: Optional[str],
    messages: list[dict],
    persona_id: Optional[str],
) -> list[str]:
    """Return topic terms to look up in the graph.

    Matching is driven by existing product/campaign/brand/entity nodes, using
    slug, title, tags and optional metadata aliases/synonyms. Recent message
    history is *always* included so the sidebar surfaces relevant knowledge
    even when the latest client message is short (e.g., a name or yes/no).
    """
    user_terms: list[str] = []
    if user_text:
        user_terms = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'-]{2,}", user_text.lower())
    msg_terms = _candidate_terms_from_messages(messages)

    seen_lower: set[str] = set()
    raw_terms: list[str] = []
    for t in [*user_terms, *msg_terms]:
        key = t.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        raw_terms.append(t)

    if not raw_terms:
        return []

    raw_blob = _fold(" ".join(raw_terms))
    raw_set = set(re.findall(r"[a-z0-9][a-z0-9'-]{1,}", raw_blob))

    detected: list[str] = []

    # Graph-driven: any topic node title, slug, tag, or alias that appears.
    try:
        canon_nodes = supabase_client.list_knowledge_nodes_by_type(
            ["product", "campaign", "brand", "entity", "audience"], persona_id=persona_id, limit=500,
        )
        for n in canon_nodes:
            slug = _fold(n.get("slug") or "")
            title = _fold(n.get("title") or "")
            tags = [_fold(t) for t in _normalize_tags(n.get("tags"))]
            meta = n.get("metadata") or {}
            aliases = [_fold(a) for a in _as_list(meta.get("aliases") or meta.get("synonyms")) if a]
            slug_parts = [p for p in slug.split("-") if len(p) >= 3]
            # Substring match (slug/title in blob) handles exact mentions.
            # Prefix match against tokens handles PT plural/singular pairs
            # (e.g., "modal" vs "modais", "papel" vs "papeis").
            matched = (
                (slug and slug in raw_blob)
                or (title and title in raw_blob)
                or any(part in raw_set for part in slug_parts)
                or any(_prefix_overlap(part, raw_set) for part in slug_parts)
                or (slug and _prefix_overlap(slug, raw_set))
                or any(tag and (tag in raw_set or tag in raw_blob or _prefix_overlap(tag, raw_set)) for tag in tags)
                or any(alias and (alias in raw_blob or _prefix_overlap(alias, raw_set)) for alias in aliases)
            )
            if matched:
                if n.get("title") and n["title"] not in detected:
                    detected.append(n["title"])
    except Exception as exc:
        logger.warning("_detect_terms graph lookup failed: %s", exc)

    out: list[str] = []
    seen: set[str] = set()
    for term in detected:
        key = _fold(term)
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _infer_persona_from_messages(
    lead_ref: int,
    user_text: Optional[str],
    interesse_produto: Optional[str],
    min_dominance: float = 0.70,
    min_hits: int = 1,
) -> Optional[str]:
    """Walk the knowledge graph to infer which persona owns the conversation.

    Strategy:
      1. Pull recent messages + lead.interesse_produto + user_text.
      2. Tokenize into candidate terms (same logic as _detect_terms).
      3. Match each term against ALL personas' knowledge_nodes (no scope).
      4. Score per-persona by counting matched nodes (weighted by node_type
         priority — product/brand/campaign/entity > faq/copy > tag/mention).
      5. Return the persona_id whose share of total hits >= min_dominance and
         whose absolute hit count >= min_hits. Otherwise None.

    This is intentionally conservative — when the conversation is ambiguous
    or short, we keep the safety block instead of guessing a persona and
    leaking another client's knowledge.
    """
    try:
        messages = supabase_client.get_messages(str(lead_ref), limit=30) or []
    except Exception:
        messages = []

    blob_parts: list[str] = []
    if user_text:
        blob_parts.append(user_text)
    if interesse_produto:
        blob_parts.append(interesse_produto)
    blob_parts.extend((m or {}).get("texto", "") for m in messages)
    blob = " ".join(p for p in blob_parts if p)
    if not blob.strip():
        return None

    # Tokenize same way _detect_terms does — but here we run global lookup.
    raw_tokens = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'-]{2,}", blob.lower())
    if not raw_tokens:
        return None
    raw_blob = _fold(" ".join(raw_tokens))
    raw_set = set(re.findall(r"[a-z0-9][a-z0-9'-]{1,}", raw_blob))

    # Pull canonical topic nodes globally and score by persona.
    try:
        canon_nodes = supabase_client.list_knowledge_nodes_by_type(
            ["product", "campaign", "brand", "entity"], persona_id=None, limit=1000,
        )
    except Exception:
        return None

    # Score map: persona_id -> weighted hits
    type_weight = {"product": 4, "brand": 3, "campaign": 3, "entity": 2}
    persona_score: dict[str, float] = {}
    matched_per_persona: dict[str, int] = {}

    for n in canon_nodes:
        pid = n.get("persona_id")
        if not pid:
            continue
        slug = _fold(n.get("slug") or "")
        title = _fold(n.get("title") or "")
        tags = [_fold(t) for t in _normalize_tags(n.get("tags"))]
        meta = n.get("metadata") or {}
        aliases = [_fold(a) for a in _as_list(meta.get("aliases") or meta.get("synonyms")) if a]
        slug_parts = [p for p in slug.split("-") if len(p) >= 3]
        matched = (
            (slug and slug in raw_blob)
            or (title and title in raw_blob)
            or any(part in raw_set for part in slug_parts)
            or any(_prefix_overlap(part, raw_set) for part in slug_parts)
            or (slug and _prefix_overlap(slug, raw_set))
            or any(tag and (tag in raw_set or tag in raw_blob or _prefix_overlap(tag, raw_set)) for tag in tags)
            or any(alias and (alias in raw_blob or _prefix_overlap(alias, raw_set)) for alias in aliases)
        )
        if matched:
            w = type_weight.get(n.get("node_type", ""), 1)
            persona_score[pid] = persona_score.get(pid, 0.0) + w
            matched_per_persona[pid] = matched_per_persona.get(pid, 0) + 1

    if not persona_score:
        return None
    total = sum(persona_score.values())
    best_pid, best_score = max(persona_score.items(), key=lambda kv: kv[1])
    dominance = best_score / total if total > 0 else 0
    if dominance >= min_dominance and matched_per_persona.get(best_pid, 0) >= min_hits:
        logger.info(
            "knowledge_graph: inferred persona for lead_ref=%s -> %s (dominance=%.2f, hits=%d)",
            lead_ref, best_pid, dominance, matched_per_persona.get(best_pid),
        )
        return best_pid
    return None


def get_chat_context(
    lead_ref: Optional[int],
    persona_id: Optional[str] = None,
    user_text: Optional[str] = None,
    limit: int = 12,
) -> dict:
    """Resolve a knowledge bundle relevant to a lead's conversation.

    Output shape (always present, even when graph is empty):
        {query_terms, nodes, edges, kb_entries, assets, summary}
    """
    lead_data: dict = {}
    if lead_ref:
        try:
            lead_data = supabase_client.get_lead_by_ref(int(lead_ref)) or {}
        except Exception:
            lead_data = {}
    if not persona_id:
        persona_id = lead_data.get("persona_id")

    persona_was_inferred = False
    if not persona_id and lead_ref:
        # Walk the graph: try to infer persona from message history. Only
        # accepted when one persona dominates the matches — otherwise we
        # keep the safety block to avoid leaking another client's knowledge.
        inferred = _infer_persona_from_messages(
            int(lead_ref),
            user_text=user_text,
            interesse_produto=(lead_data.get("interesse_produto") or "").strip() or None,
        )
        if inferred:
            persona_id = inferred
            persona_was_inferred = True
            # Backfill the lead so downstream calls (and future requests)
            # don't repeat this work. Best-effort: ignore failures.
            try:
                supabase_client.update_lead(int(lead_ref), {"persona_id": inferred})
            except Exception as exc:
                logger.warning("knowledge_graph: persona backfill failed for lead %s: %s", lead_ref, exc)

    if not persona_id:
        # Sem persona definida (lead sem vínculo OU chamada sem escopo) o
        # contexto não pode ser global — devolveríamos conhecimento de outro
        # cliente. Bloqueia explicitamente.
        reason = (
            "Lead sem persona vinculada e conversa não bate com nenhum cliente conhecido"
            if lead_ref
            else "Persona não especificada"
        )
        return {
            "query_terms": [],
            "entities": [],
            "intent": "fallback_text_search",
            "nodes": [],
            "edges": [],
            "kb_entries": [],
            "assets": [],
            "similar": [],
            "validated": {"nodes": [], "kb_entries": [], "assets": []},
            "unvalidated": {"nodes": [], "kb_entries": [], "assets": []},
            "summary": f"{reason}; contexto de conhecimento bloqueado para evitar mistura entre clientes.",
            "persona_inferred": False,
        }
    lead_interest = (lead_data.get("interesse_produto") or "").strip()

    # 1. Recent messages provide context when no explicit q.
    messages: list[dict] = []
    if lead_ref:
        try:
            messages = supabase_client.get_messages(str(lead_ref), limit=20) or []
        except Exception:
            messages = []

    query_text = " ".join(x for x in [user_text, lead_interest] if x)
    terms = _detect_terms(query_text or None, messages, persona_id)

    # 2. Match nodes by each term.
    seed_nodes: dict[str, dict] = {}
    for term in terms:
        try:
            for n in supabase_client.find_knowledge_nodes(term, persona_id=persona_id, limit=8):
                seed_nodes[n["id"]] = n
        except Exception as exc:
            logger.warning("find_knowledge_nodes failed for %r: %s", term, exc)

    # 3. Neighbours. We expand two hops so topic nodes can surface FAQ,
    # briefing and source item subnodes without requiring every item to match
    # the text directly.
    nodes: list[dict] = []
    edges: list[dict] = []
    if seed_nodes:
        try:
            n_full, e_full = supabase_client.get_knowledge_neighbors(list(seed_nodes.keys()))
            node_map = {n["id"]: n for n in n_full if n.get("id")}
            edge_map = {e["id"]: e for e in e_full if e.get("id")}
            if node_map:
                n2, e2 = supabase_client.get_knowledge_neighbors(list(node_map.keys()))
                node_map.update({n["id"]: n for n in n2 if n.get("id")})
                edge_map.update({e["id"]: e for e in e2 if e.get("id")})
            nodes = list(node_map.values())[:limit * 6]
            edges = list(edge_map.values())[: limit * 10]
        except Exception as exc:
            logger.warning("get_knowledge_neighbors failed: %s", exc)
            nodes = list(seed_nodes.values())
            edges = []

    nodes = [_decorate_node(n) for n in nodes]
    existing_source_ids = {str(n.get("source_id")) for n in nodes if n.get("source_id")}
    nodes.extend(_fallback_nodes_from_tables(terms, persona_id, existing_source_ids))

    # 3.b BFS over edges so every node carries graph_distance + path back to
    # the nearest seed. Fallback nodes (no edges) keep distance=None.
    distance_map, path_map = _compute_graph_distances(
        seed_ids=set(seed_nodes.keys()),
        nodes=nodes,
        edges=edges,
    )
    for n in nodes:
        nid = n.get("id")
        if nid in distance_map:
            n["graph_distance"] = distance_map[nid]
            n["path"] = path_map.get(nid) or []
            n["path_slugs"] = [step.get("slug") for step in (path_map.get(nid) or [])]
            n["path_relations"] = [
                step.get("relation_type")
                for step in (path_map.get(nid) or [])
                if step.get("relation_type")
            ]
        else:
            # Fallback nodes / unreached nodes: keep field present but null
            n["graph_distance"] = None
            n["path"] = []
            n["path_slugs"] = []
            n["path_relations"] = []

    # 4. Split into convenient buckets for the UI.
    by_type: dict[str, list[dict]] = {}
    for n in nodes:
        by_type.setdefault(n.get("node_type", ""), []).append(n)

    kb_entry_nodes = [
        n for n in nodes
        if n.get("source_table") == "kb_entries"
        or n.get("node_type") in {"kb_entry", "faq", "copy"}
    ]
    # Batch fetch — avoids N+1 round-trip per kb_entry node.
    kb_source_ids = [str(n["source_id"]) for n in kb_entry_nodes if n.get("source_id")]
    try:
        kb_rows_by_id = supabase_client.get_kb_entries_by_ids(kb_source_ids) if kb_source_ids else {}
    except Exception as exc:
        logger.warning("get_kb_entries_by_ids failed: %s", exc)
        kb_rows_by_id = {}

    kb_entries: list[dict] = []
    for n in kb_entry_nodes:
        sid = n.get("source_id")
        row = kb_rows_by_id.get(str(sid)) if sid else None
        if row:
            row_node_type = _tipo_to_node_type(row.get("tipo") or row.get("categoria") or "") or n.get("node_type")
            kb_entries.append({
                **row,
                "node_type": row_node_type,
                "validation_status": "validated" if _is_validated_source("kb_entries", row.get("status"), row_node_type) else "pending",
                "validated": _is_validated_source("kb_entries", row.get("status"), row_node_type),
                "link_target": n.get("link_target") or _link_target(n),
            })
            continue
        # Fallback: project the node itself (when no kb row backs it).
        kb_entries.append({
            "id": n.get("id"),
            "titulo": n.get("title"),
            "conteudo": n.get("summary") or "",
            "tipo": n.get("node_type"),
            "tags": _normalize_tags(n.get("tags")),
            "node_type": n.get("node_type"),
            "validation_status": n.get("validation_status") or "pending",
            "validated": bool(n.get("validated")),
            "link_target": n.get("link_target"),
        })

    assets: list[dict] = []
    for n in by_type.get("asset", []):
        meta = n.get("metadata") or {}
        path = meta.get("file_path")
        url = f"/api-brain/knowledge/file?path={path}" if path else None
        assets.append({
            "id": n.get("id"),
            "title": n.get("title"),
            "asset_type": meta.get("asset_type"),
            "asset_function": meta.get("asset_function"),
            "file_path": path,
            "url": url,
            "tags": _normalize_tags(n.get("tags")),
            "validation_status": n.get("validation_status") or "pending",
            "validated": bool(n.get("validated")),
            "link_target": n.get("link_target") or url,
        })

    # 5. Entities = the seed nodes that originally matched the query.
    entities = [
        {
            "id": n.get("id"),
            "type": n.get("node_type"),
            "slug": n.get("slug"),
            "title": n.get("title"),
            "link_target": _link_target(n),
        }
        for n in seed_nodes.values()
    ]

    # 6. Intent — simple keyword heuristic over the user text, then graph hits.
    intent = _detect_intent(user_text or " ".join(((m or {}).get("texto") or "") for m in messages),
                            by_type, assets)

    # 7. Human-readable summary.
    parts: list[str] = []
    if terms:
        parts.append("Termos detectados: " + ", ".join(terms))
    products = [n["title"] for n in by_type.get("product", [])]
    campaigns = [n["title"] for n in by_type.get("campaign", [])]
    if products:
        parts.append("Produtos: " + ", ".join(products))
    if campaigns:
        parts.append("Campanhas: " + ", ".join(campaigns))
    if assets:
        parts.append(f"{len(assets)} asset(s) relacionado(s)")
    summary = " · ".join(parts)

    validated_nodes = [n for n in nodes if n.get("validated")]
    unvalidated_nodes = [n for n in nodes if not n.get("validated")]

    # 8. Similarity ranking — strictly by graph_distance, with type as tiebreak
    # (product/campaign/faq/copy/asset before tag/mention). Seeds excluded.
    seed_id_set = set(seed_nodes.keys())
    type_priority = {"product": 0, "campaign": 1, "brand": 1, "faq": 2,
                     "copy": 3, "asset": 4, "briefing": 5, "rule": 6,
                     "tone": 6, "audience": 7, "tag": 9, "mention": 9}
    similar = sorted(
        [
            {
                "node_id": n.get("id"),
                "node_type": n.get("node_type"),
                "slug": n.get("slug"),
                "title": n.get("title"),
                "graph_distance": n.get("graph_distance"),
                "path": n.get("path") or [],
                "path_slugs": n.get("path_slugs") or [],
                "path_relations": n.get("path_relations") or [],
                "validated": bool(n.get("validated")),
                "link_target": n.get("link_target"),
            }
            for n in nodes
            if n.get("id") not in seed_id_set
            and n.get("graph_distance") is not None
        ],
        key=lambda r: (
            r["graph_distance"] if r["graph_distance"] is not None else 99,
            type_priority.get(r["node_type"], 8),
            (r["title"] or "").lower(),
        ),
    )[: limit * 2]

    return {
        "query_terms": terms,
        "entities": entities,
        "intent": intent,
        "nodes": nodes,
        "edges": edges,
        "kb_entries": kb_entries,
        "assets": assets,
        "similar": similar,
        "validated": {
            "nodes": validated_nodes,
            "kb_entries": [e for e in kb_entries if e.get("validated")],
            "assets": [a for a in assets if a.get("validated")],
        },
        "unvalidated": {
            "nodes": unvalidated_nodes,
            "kb_entries": [e for e in kb_entries if not e.get("validated")],
            "assets": [a for a in assets if not a.get("validated")],
        },
        "summary": summary,
        "persona_id": persona_id,
        "persona_inferred": persona_was_inferred,
    }


_INTENT_ASSET_KEYWORDS = re.compile(
    r"\b(imagem|imagens|foto|fotos|asset|assets|m[ií]dia|midia|banner|hero|story|catalog|catálogo|video|v[ií]deo)\b",
    re.IGNORECASE,
)


def _detect_intent(text: str, by_type: dict, assets: list[dict]) -> str:
    """Cheap rule-based intent classifier (no LLM).

    Order of precedence:
      1. asset_request — user mentions media/images/etc
      2. product_inquiry — there's at least one product node
      3. campaign_inquiry — there's at least one campaign node
      4. kb_lookup — only KB entries matched
      5. fallback_text_search — nothing matched.
    """
    blob = (text or "").lower()
    if assets and _INTENT_ASSET_KEYWORDS.search(blob):
        return "asset_request"
    if by_type.get("product"):
        return "product_inquiry"
    if by_type.get("campaign"):
        return "campaign_inquiry"
    if by_type.get("faq") or by_type.get("copy") or by_type.get("kb_entry"):
        return "kb_lookup"
    return "fallback_text_search"
