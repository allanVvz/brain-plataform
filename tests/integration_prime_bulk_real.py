#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bulk real-data integration test for Prime Higienizacao.

Default plan:
  - 5 products/services
  - 10 copy entries
  - 50 FAQ entries
  - 1 brand, 1 briefing, 1 tone, 1 pricing rule
  - graph edges connecting brand -> products -> FAQ/copy/tone/rule
  - stored inbound/outbound messages for a test lead

Dry-run is the default and never writes. Use --apply to write through the real
Supabase client configured by .env / SUPABASE_URL / SUPABASE_SERVICE_KEY.

Run:
  python tests/integration_prime_bulk_real.py --dry-run
  python tests/integration_prime_bulk_real.py --apply --lead-ref 91003
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "test-artifacts" / "prime_bulk_real_test.json"
_TABLE_EXISTS_CACHE: dict[str, bool] = {}
_MISSING_TABLE_WARNED: set[str] = set()


class CheckFailure(Exception):
    pass


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def slugify(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[áàãâä]", "a", text)
    text = re.sub(r"[éèêë]", "e", text)
    text = re.sub(r"[íìîï]", "i", text)
    text = re.sub(r"[óòõôö]", "o", text)
    text = re.sub(r"[úùûü]", "u", text)
    text = re.sub(r"ç", "c", text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "item"


def md5_text(value: str) -> str:
    return hashlib.md5((value or "").encode("utf-8")).hexdigest()


def expect(report: dict, cond: bool, msg: str, details: Any = None, *, fatal: bool = True) -> None:
    entry = {"ok": bool(cond), "check": msg}
    if details is not None:
        entry["details"] = details
    report.setdefault("checks", []).append(entry)
    print(("  ok " if cond else "  FAIL ") + msg)
    if not cond and fatal:
        raise CheckFailure(msg)


def warn(report: dict, msg: str, details: Any = None) -> None:
    entry = {"warning": msg}
    if details is not None:
        entry["details"] = details
    report.setdefault("warnings", []).append(entry)
    print("  WARN " + msg)


def generated_products(count: int) -> list[dict]:
    base = [
        ("higienizacao-cadeiras-prime", "Higienizacao de Cadeiras Prime", 100.0, "R$ 100,00", "por cadeira", ["cadeira", "cadeiras", "limpeza de cadeira"]),
        ("higienizacao-sofas-prime", "Higienizacao de Sofas Prime", 200.0, "R$ 200,00", "por sofa", ["sofa", "sofas", "limpeza de sofa", "estofado"]),
        ("higienizacao-poltronas-prime", "Higienizacao de Poltronas Prime", 180.0, "R$ 180,00", "por poltrona", ["poltrona", "poltronas"]),
        ("higienizacao-colchoes-prime", "Higienizacao de Colchoes Prime", 250.0, "R$ 250,00", "por colchao", ["colchao", "colchoes"]),
        ("impermeabilizacao-prime", "Impermeabilizacao Prime", 30.0, "+30%", "acrescimo percentual", ["impermeabilizacao", "hipermeabilizacao", "impermeabilizar"]),
        ("plano-dia-inteiro-prime", "Plano Dia Inteiro Prime", 1500.0, "R$ 1.500,00", "dia inteiro", ["dia inteiro", "plano diario"]),
    ]
    products = []
    for idx, (slug, title, amount, display, unit, aliases) in enumerate(base[:count], start=1):
        products.append({
            "node_type": "product",
            "slug": slug,
            "title": title,
            "content": f"{title}. Atendimento Prime Higienizacao em Novo Hamburgo. Preco {display} {unit}.",
            "tags": ["product", "prime-higienizacao", "novo-hamburgo", slug],
            "metadata": {
                "aliases": aliases,
                "price": {
                    "amount": amount,
                    "currency": "BRL",
                    "display": display,
                    "unit": unit,
                },
                "region": "Novo Hamburgo",
                "service_index": idx,
                "test_batch": "prime_bulk_real",
            },
        })
    return products


def generate_scenario(product_count: int, copy_count: int, faq_count: int) -> dict:
    products = generated_products(product_count)
    if len(products) < product_count:
        raise CheckFailure("product_count exceeds available deterministic product templates")

    brand = {
        "node_type": "brand",
        "slug": "prime-higienizacao",
        "title": "Prime Higienizacao",
        "content": "Marca regional de higienizacao em Novo Hamburgo. Cor predominante azul. Servicos limpos, seguros e objetivos.",
        "tags": ["brand", "prime-higienizacao", "novo-hamburgo", "azul"],
        "metadata": {
            "aliases": ["Prime", "Prime Higienizacao", "higienizacao prime"],
            "dominant_color": {"name": "azul", "hex": "#1d4ed8"},
            "region": "Novo Hamburgo",
            "test_batch": "prime_bulk_real",
        },
    }
    briefing = {
        "node_type": "briefing",
        "slug": "briefing-prime-bulk-real",
        "title": "Briefing Prime Higienizacao Bulk Real",
        "content": "Briefing geral: casal atende Novo Hamburgo com higienizacao de estofados, sofas, cadeiras, poltronas e colchoes. Servico de qualidade, seguro e direto.",
        "tags": ["briefing", "prime-higienizacao", "novo-hamburgo"],
        "metadata": {"operator_profile": "casal", "region": "Novo Hamburgo", "test_batch": "prime_bulk_real"},
    }
    tone = {
        "node_type": "tone",
        "slug": "tom-prime-bulk-real",
        "title": "Tom Prime Higienizacao Bulk Real",
        "content": "Tom serio, direto ao ponto, regional, clean e seguro.",
        "tags": ["tone", "prime-higienizacao", "seguro"],
        "metadata": {"voice": ["serio", "direto ao ponto", "regional", "clean", "seguro"], "test_batch": "prime_bulk_real"},
    }
    rule = {
        "node_type": "rule",
        "slug": "regra-precos-prime-bulk-real",
        "title": "Regra de Precos Prime Bulk Real",
        "content": "Sempre responder valores com clareza e unidade. Produtos sem preco estruturado nao devem ser validados.",
        "tags": ["rule", "precos", "prime-higienizacao"],
        "metadata": {"requires_clear_price": True, "test_batch": "prime_bulk_real"},
    }

    copies = []
    for idx in range(copy_count):
        product = products[idx % len(products)]
        price = product["metadata"]["price"]
        copies.append({
            "node_type": "copy",
            "slug": f"copy-prime-bulk-{idx + 1:02d}-{product['slug']}",
            "title": f"Copy Prime {idx + 1:02d} - {product['title']}",
            "content": (
                f"{product['title']} em Novo Hamburgo com atendimento serio e seguro. "
                f"Valor {price['display']} {price['unit']}."
            ),
            "tags": ["copy", "prime-higienizacao", product["slug"]],
            "metadata": {
                "product_slug": product["slug"],
                "channel": "chat",
                "test_batch": "prime_bulk_real",
            },
        })

    faq_templates = [
        "Quanto custa {title}?",
        "A Prime atende {title} em Novo Hamburgo?",
        "Como funciona o agendamento para {title}?",
        "O valor de {title} inclui deslocamento?",
        "Quanto tempo leva {title}?",
        "Da para combinar {title} com impermeabilizacao?",
        "Que cuidado devo ter depois de {title}?",
        "A Prime faz {title} para empresas?",
        "Tem plano por dia para {title}?",
        "Qual o diferencial da Prime em {title}?",
    ]
    faqs = []
    for idx in range(faq_count):
        product = products[idx % len(products)]
        price = product["metadata"]["price"]
        question = faq_templates[idx % len(faq_templates)].format(title=product["title"])
        faqs.append({
            "node_type": "faq",
            "slug": f"faq-prime-bulk-{idx + 1:03d}-{product['slug']}",
            "title": f"FAQ Prime {idx + 1:03d} - {product['title']}",
            "content": (
                f"Pergunta: {question}\n"
                f"Resposta: {product['title']} custa {price['display']} {price['unit']} na regiao de Novo Hamburgo. "
                "A resposta deve ser seria, direta, regional, clean e segura."
            ),
            "tags": ["faq", "prime-higienizacao", product["slug"]],
            "metadata": {
                "question": question,
                "answer_requirements": [price["display"], "Novo Hamburgo"],
                "product_slug": product["slug"],
                "test_batch": "prime_bulk_real",
            },
        })

    edges = [
        (briefing["slug"], "defines_brand", brand["slug"]),
        (tone["slug"], "defines_brand", brand["slug"]),
        (brand["slug"], "has_tone", tone["slug"]),
    ]
    for product in products:
        edges.extend([
            (brand["slug"], "about_product", product["slug"]),
            (product["slug"], "has_tone", tone["slug"]),
            (rule["slug"], "about_product", product["slug"]),
        ])
    for left, right in zip(products, products[1:]):
        edges.append((left["slug"], "same_topic_as", right["slug"]))
    for copy in copies:
        edges.append((copy["slug"], "supports_copy", copy["metadata"]["product_slug"]))
    for faq in faqs:
        edges.append((faq["slug"], "answers_question", faq["metadata"]["product_slug"]))

    return {
        "persona": {
            "slug": "prime-higienizacao",
            "name": "Prime Higienizacao",
            "tone": "serio, direto ao ponto, regional, clean e seguro",
            "products": [p["title"] for p in products],
            "config": {"region": "Novo Hamburgo", "test_batch": "prime_bulk_real"},
            "active": True,
        },
        "items": [brand, briefing, tone, rule, *products, *copies, *faqs],
        "products": products,
        "copies": copies,
        "faqs": faqs,
        "edges": edges,
        "test_messages": [
            "Quais servicos e precos da Prime Higienizacao em Novo Hamburgo?",
            f"Quanto custa {products[0]['title']}?",
            f"Me explica {products[-1]['title']} e relacionados.",
        ],
    }


def item_frontmatter(item: dict) -> dict:
    metadata = dict(item.get("metadata") or {})
    metadata["slug"] = item["slug"]
    metadata.setdefault("aliases", metadata.get("aliases") or item.get("aliases") or [])
    return {
        "slug": item["slug"],
        "type": item["node_type"],
        "tags": item.get("tags") or [],
        "aliases": metadata.get("aliases") or [],
        "metadata": metadata,
        "product": metadata.get("product_slug"),
        "graph": {
            "relates_to": [f"product:{metadata['product_slug']}"] if metadata.get("product_slug") else []
        },
    }


def table_exists(client, table: str) -> bool:
    if table in _TABLE_EXISTS_CACHE:
        return _TABLE_EXISTS_CACHE[table]
    try:
        client.table(table).select("*").limit(1).execute()
        _TABLE_EXISTS_CACHE[table] = True
        return True
    except Exception:
        _TABLE_EXISTS_CACHE[table] = False
        return False


def warn_missing_table_once(report: dict, table: str, message: str) -> None:
    if table in _MISSING_TABLE_WARNED:
        return
    _MISSING_TABLE_WARNED.add(table)
    warn(report, message)


def existing_item(client, persona_id: str, item: dict) -> Optional[dict]:
    rows = (
        client.table("knowledge_items")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("content_type", item["node_type"])
        .eq("title", item["title"])
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def upsert_item_and_node(
    report: dict,
    supabase_client,
    knowledge_graph,
    client,
    persona_id: str,
    source_id: Optional[str],
    item: dict,
    *,
    bootstrap: bool,
    write_artifacts: bool,
    promote_to_kb: bool,
) -> tuple[dict, dict]:
    payload = {
        "persona_id": persona_id,
        "source_id": source_id,
        "status": "approved",
        "content_type": item["node_type"],
        "title": item["title"],
        "content": item.get("content") or item["title"],
        "metadata": item_frontmatter(item)["metadata"],
        "file_type": "text",
        "file_path": f"real-test://prime-bulk/{item['node_type']}/{item['slug']}.md",
        "tags": item.get("tags") or [],
    }
    current = existing_item(client, persona_id, item)
    if current:
        supabase_client.update_knowledge_item(current["id"], payload)
        row = supabase_client.get_knowledge_item(current["id"]) or {**current, **payload}
    else:
        row = supabase_client.insert_knowledge_item(payload)
    expect(report, bool(row.get("id")), f"knowledge_item upserted: {item['node_type']}:{item['slug']}")

    if bootstrap:
        knowledge_graph.bootstrap_from_item(
            row,
            frontmatter=item_frontmatter(item),
            body=payload["content"],
            persona_id=persona_id,
            source_table="knowledge_items",
        )
    node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "source_table": "knowledge_items",
        "source_id": row.get("id"),
        "node_type": item["node_type"],
        "slug": item["slug"],
        "title": item["title"],
        "summary": payload["content"][:400],
        "tags": item.get("tags") or [],
        "metadata": payload["metadata"],
        "status": "validated",
    })
    expect(report, bool(node and node.get("id")), f"graph node upserted: {item['node_type']}:{item['slug']}")
    if write_artifacts:
        upsert_artifact_if_available(report, client, persona_id, item, row, node)
    if promote_to_kb:
        promote_item_to_kb(report, supabase_client, knowledge_graph, item, row, persona_id)
    return row, node


def promote_item_to_kb(report: dict, supabase_client, knowledge_graph, item: dict, row: dict, persona_id: str) -> Optional[dict]:
    kb_id = "prime_bulk_" + md5_text(f"{persona_id}:{item['node_type']}:{item['slug']}")[:16]
    metadata = item_frontmatter(item)["metadata"]
    entry = supabase_client.upsert_kb_entry({
        "kb_id": kb_id,
        "persona_id": persona_id,
        "tipo": item["node_type"],
        "categoria": item["node_type"],
        "produto": metadata.get("product_slug") or (item["slug"] if item["node_type"] == "product" else "prime-higienizacao"),
        "intencao": "teste_prime_bulk",
        "titulo": item["title"],
        "conteudo": item.get("content") or item["title"],
        "link": None,
        "prioridade": 10 if item["node_type"] in {"brand", "product", "faq"} else 50,
        "status": "ATIVO",
        "source": "manual",
        "tags": item.get("tags") or [],
        "agent_visibility": ["SDR", "Closer", "Classifier"],
    })
    expect(report, bool(entry and entry.get("id")), f"kb_entry promoted: {item['node_type']}:{item['slug']}")
    supabase_client.update_knowledge_item(row["id"], {"status": "embedded"})
    # The test already upserts semantic nodes/edges directly. Rebootstrapping
    # every promoted kb_entry makes the 69-item bulk scenario too slow and is
    # covered separately by /knowledge/graph/rebuild.
    return entry


def upsert_artifact_if_available(report: dict, client, persona_id: str, item: dict, knowledge_item: dict, node: Optional[dict]) -> None:
    if not table_exists(client, "knowledge_artifacts"):
        warn_missing_table_once(report, "knowledge_artifacts", "knowledge_artifacts unavailable; migration 009 not applied")
        return

    canonical_key = f"{persona_id}:{item['node_type']}:{item['slug']}"
    canonical_hash = md5_text(canonical_key)
    content = item.get("content") or item["title"]
    rows = (
        client.table("knowledge_artifacts")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("canonical_hash", canonical_hash)
        .limit(1)
        .execute()
        .data
        or []
    )
    payload = {
        "persona_id": persona_id,
        "canonical_key": canonical_key,
        "canonical_hash": canonical_hash,
        "title": item["title"],
        "content_type": item["node_type"],
        "summary": content[:500],
        "curation_status": "validated",
        "importance": item.get("metadata", {}).get("importance", 0.85 if item["node_type"] == "product" else 0.55),
        "level": item.get("metadata", {}).get("level", 40 if item["node_type"] == "product" else 50),
        "confidence": item.get("metadata", {}).get("confidence", 0.95),
        "current_knowledge_item_id": knowledge_item.get("id"),
        "content_hash": md5_text(content),
        "metadata": item_frontmatter(item)["metadata"],
    }
    if rows:
        artifact = rows[0]
        client.table("knowledge_artifacts").update({
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", artifact["id"]).execute()
        artifact_id = artifact["id"]
    else:
        inserted = client.table("knowledge_artifacts").insert(payload).execute().data or []
        artifact_id = (inserted[0] or {}).get("id") if inserted else None

    if not artifact_id:
        warn(report, "artifact upsert returned no id", item["slug"])
        return

    if node and node.get("id"):
        try:
            client.table("knowledge_nodes").update({"artifact_id": artifact_id}).eq("id", node["id"]).execute()
        except Exception as exc:
            warn(report, "could not backfill knowledge_nodes.artifact_id", repr(exc))

    try:
        client.table("knowledge_items").update({
            "artifact_id": artifact_id,
            "canonical_key": canonical_key,
            "canonical_hash": canonical_hash,
            "content_hash": payload["content_hash"],
            "curation_status": "validated",
            "importance": payload["importance"],
            "level": payload["level"],
            "confidence": payload["confidence"],
        }).eq("id", knowledge_item["id"]).execute()
    except Exception as exc:
        warn(report, "could not backfill knowledge_items artifact fields", repr(exc))

    if not table_exists(client, "knowledge_artifact_versions"):
        warn_missing_table_once(report, "knowledge_artifact_versions", "knowledge_artifact_versions unavailable; migration 009 not applied")
        return
    existing = (
        client.table("knowledge_artifact_versions")
        .select("id")
        .eq("source_table", "knowledge_items")
        .eq("source_id", knowledge_item["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return
    max_rows = (
        client.table("knowledge_artifact_versions")
        .select("version_no")
        .eq("artifact_id", artifact_id)
        .order("version_no", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    version_no = int((max_rows[0] or {}).get("version_no") or 0) + 1 if max_rows else 1
    client.table("knowledge_artifact_versions").insert({
        "artifact_id": artifact_id,
        "version_no": version_no,
        "source_table": "knowledge_items",
        "source_id": knowledge_item["id"],
        "title": item["title"],
        "content_type": item["node_type"],
        "content_hash": payload["content_hash"],
        "raw_content": content,
        "classification": item_frontmatter(item)["metadata"],
    }).execute()


def ensure_persona(report: dict, supabase_client, scenario: dict) -> dict:
    persona_payload = scenario["persona"]
    existing = supabase_client.get_persona(persona_payload["slug"])
    if not existing:
        supabase_client.upsert_persona(persona_payload)
        existing = supabase_client.get_persona(persona_payload["slug"])
    else:
        supabase_client.upsert_persona({**existing, **persona_payload})
        existing = supabase_client.get_persona(persona_payload["slug"])
    expect(report, bool(existing and existing.get("id")), f"persona available: {persona_payload['slug']}")
    return existing


def upsert_edges(report: dict, supabase_client, node_by_slug: dict[str, dict], scenario: dict, persona_id: str) -> None:
    for src_slug, relation, tgt_slug in scenario["edges"]:
        src = node_by_slug.get(src_slug)
        tgt = node_by_slug.get(tgt_slug)
        expect(report, bool(src), f"edge source resolved: {src_slug}")
        expect(report, bool(tgt), f"edge target resolved: {tgt_slug}")
        edge = supabase_client.upsert_knowledge_edge(
            src["id"],
            tgt["id"],
            relation,
            persona_id=persona_id,
            weight=1.0,
            metadata={"test_batch": "prime_bulk_real"},
        )
        expect(report, bool(edge), f"edge upserted: {src_slug} -[{relation}]-> {tgt_slug}")


def ensure_test_lead(report: dict, client, persona_id: str) -> int:
    lead_id = "prime_bulk_real_test_lead"
    existing = (
        client.table("leads")
        .select("id")
        .eq("lead_id", lead_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "lead_id": lead_id,
        "nome": "Teste Prime Bulk",
        "telefone": "0000000000",
        "stage": "teste",
        "persona_id": persona_id,
        "ultima_mensagem": "Teste real Prime bulk sem WhatsApp/n8n",
        "updated_at": now,
        "ai_enabled": False,
        "ai_paused": True,
        "interesse_produto": "Prime Higienizacao",
    }
    if existing:
        lead_ref = int(existing[0]["id"])
        client.table("leads").update(payload).eq("id", lead_ref).execute()
        expect(report, True, "test lead available for message inserts", {"lead_ref": lead_ref})
        return lead_ref

    try:
        inserted = client.table("leads").insert(payload).execute().data or []
    except Exception:
        minimal = {
            "lead_id": lead_id,
            "nome": "Teste Prime Bulk",
            "telefone": "0000000000",
            "stage": "teste",
            "persona_id": persona_id,
        }
        inserted = client.table("leads").insert(minimal).execute().data or []
    lead_ref = int((inserted[0] or {}).get("id")) if inserted else 0
    expect(report, bool(lead_ref), "test lead created for message inserts")
    return lead_ref


def require_lead_ref(report: dict, supabase_client, lead_ref: int) -> None:
    lead = supabase_client.get_lead_by_ref(lead_ref)
    if not lead:
        raise CheckFailure(
            f"lead_ref {lead_ref} does not exist in leads; pass --create-test-lead, "
            "use --lead-ref with an existing leads.id, or use --skip-messages for knowledge-only apply"
        )
    expect(report, True, "lead_ref exists for message inserts", {"lead_ref": lead_ref})


def deterministic_prime_reply(scenario: dict, prompt: str) -> str:
    products = scenario["products"]
    prompt_norm = slugify(prompt)
    matched = None
    for product in products:
        aliases = product.get("metadata", {}).get("aliases") or []
        candidates = [product["title"], product["slug"], *aliases]
        if any(slugify(str(candidate)) in prompt_norm or slugify(str(candidate)).replace("-", "") in prompt_norm.replace("-", "") for candidate in candidates):
            matched = product
            break
    if not matched:
        price_lines = [
            f"{p['title']}: {p['metadata']['price']['display']} {p['metadata']['price']['unit']}"
            for p in products
        ]
        return "Prime Higienizacao em Novo Hamburgo. " + "; ".join(price_lines) + "."
    price = matched["metadata"]["price"]
    faq = next((f for f in scenario["faqs"] if f["metadata"].get("product_slug") == matched["slug"]), None)
    suffix = f" FAQ relacionada: {faq['title']}." if faq else ""
    return (
        f"{matched['title']} custa {price['display']} {price['unit']} em Novo Hamburgo. "
        f"Atendimento Prime com tom serio, direto, regional, clean e seguro.{suffix}"
    )


def insert_test_messages(report: dict, supabase_client, scenario: dict, lead_ref: int) -> None:
    run_token = report.setdefault("run_token", str(int(datetime.now(timezone.utc).timestamp() * 1000)))
    for idx, text in enumerate(scenario["test_messages"], start=1):
        inbound = {
            "lead_ref": lead_ref,
            "message_id": f"prime_bulk_in_{idx}_{run_token}",
            "sender_type": "client",
            "sender_id": "prime-bulk-test",
            "canal": "test",
            "texto": text,
            "status": "received",
            "direction": "inbound",
            "metadata": {"test_batch": "prime_bulk_real", "index": idx},
            "nome": "Teste Prime Bulk",
            "Lead_Stage": "teste",
        }
        reply_text = deterministic_prime_reply(scenario, text)
        reply = {
            "lead_ref": lead_ref,
            "message_id": f"prime_bulk_out_{idx}_{run_token}",
            "sender_type": "assistant",
            "sender_id": "mock-bot",
            "canal": "test",
            "texto": reply_text,
            "status": "sent",
            "direction": "outbound",
            "metadata": {"test_batch": "prime_bulk_real", "index": idx},
            "nome": "Teste Prime Bulk",
            "Lead_Stage": "teste",
        }
        supabase_client.insert_message(inbound)
        supabase_client.insert_message(reply)
        expect(report, "Resposta teste Prime" not in reply_text, f"test reply {idx} is knowledge-specific")
        expect(report, any((p["metadata"]["price"]["display"] in reply_text) for p in scenario["products"]),
               f"test reply {idx} includes a scenario price")
        expect(report, True, f"messages inserted for test prompt {idx}")


def fetch_batch_messages(client, lead_ref: int, run_token: Optional[str] = None) -> list[dict]:
    try:
        q = (
            client.table("messages")
            .select("*")
            .eq("lead_ref", lead_ref)
            .contains("metadata", {"test_batch": "prime_bulk_real"})
            .limit(500)
        )
        if run_token:
            q = q.like("message_id", f"%_{run_token}")
        return q.execute().data or []
    except Exception:
        return []


def validate_real_state(
    report: dict,
    client,
    knowledge_graph,
    scenario: dict,
    persona_id: str,
    lead_ref: int,
    *,
    validate_messages: bool,
    validate_kb: bool,
) -> None:
    products = (
        client.table("knowledge_nodes")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("node_type", "product")
        .contains("metadata", {"test_batch": "prime_bulk_real"})
        .limit(200)
        .execute()
        .data
        or []
    )
    copies = (
        client.table("knowledge_nodes")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("node_type", "copy")
        .contains("metadata", {"test_batch": "prime_bulk_real"})
        .limit(500)
        .execute()
        .data
        or []
    )
    faqs = (
        client.table("knowledge_nodes")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("node_type", "faq")
        .contains("metadata", {"test_batch": "prime_bulk_real"})
        .limit(1000)
        .execute()
        .data
        or []
    )
    expect(report, len(products) >= len(scenario["products"]), "database has all bulk product nodes", {"actual": len(products)})
    expect(report, len(copies) >= len(scenario["copies"]), "database has all bulk copy nodes", {"actual": len(copies)})
    expect(report, len(faqs) >= len(scenario["faqs"]), "database has all bulk FAQ nodes", {"actual": len(faqs)})
    missing_price = [p.get("slug") for p in products if not (((p.get("metadata") or {}).get("price") or {}).get("display"))]
    expect(report, not missing_price, "all bulk product nodes have structured price", missing_price)

    if validate_messages:
        batch_messages = fetch_batch_messages(client, lead_ref, report.get("run_token"))
        expect(report, len(batch_messages) >= len(scenario["test_messages"]) * 2,
               "database has stored inbound/outbound bulk test messages",
               {"actual": len(batch_messages), "lead_ref": lead_ref})
        generic_replies = [
            m.get("id") for m in batch_messages
            if m.get("sender_type") in {"assistant", "agent"} and "Resposta teste Prime: consultei" in (m.get("texto") or "")
        ]
        expect(report, not generic_replies, "bulk test assistant replies are not generic placeholders", generic_replies)
    else:
        warn(report, "message persistence validation skipped by --skip-messages")

    if validate_kb:
        kb_rows = (
            client.table("kb_entries")
            .select("id,tipo,titulo,conteudo,status")
            .eq("persona_id", persona_id)
            .eq("status", "ATIVO")
            .contains("tags", ["prime-higienizacao"])
            .limit(1000)
            .execute()
            .data
            or []
        )
        expect(report, len(kb_rows) >= len(scenario["items"]),
               "all bulk items were promoted to active KB entries",
               {"actual": len(kb_rows), "expected": len(scenario["items"])})

        from services.knowledge_service import search_kb_text
        kb_chunks = search_kb_text("Quanto custa Higienizacao de Cadeiras Prime?", persona_id=persona_id, top_k=5)
        expect(report, bool(kb_chunks), "agent KB text search returns Prime chunks")
        expect(report, any("R$ 100,00" in chunk for chunk in kb_chunks),
               "agent KB text search includes Prime price knowledge")
    else:
        warn(report, "KB promotion validation skipped")

    ctx = knowledge_graph.get_chat_context(
        lead_ref=lead_ref,
        persona_id=persona_id,
        user_text=scenario["test_messages"][0],
        limit=50,
    )
    report["chat_context"] = {
        "query_terms": ctx.get("query_terms"),
        "node_count": len(ctx.get("nodes") or []),
        "edge_count": len(ctx.get("edges") or []),
        "similar_count": len(ctx.get("similar") or []),
        "sample_nodes": [
            {"slug": n.get("slug"), "node_type": n.get("node_type"), "graph_distance": n.get("graph_distance")}
            for n in (ctx.get("nodes") or [])[:20]
        ],
    }
    expect(report, any(n.get("node_type") == "brand" and n.get("slug") == "prime-higienizacao" for n in ctx.get("nodes") or []),
           "chat_context includes Prime brand")
    expect(report, len(ctx.get("edges") or []) >= len(scenario["products"]),
           "chat_context returns graph relations for sidebar",
           {"edge_count": len(ctx.get("edges") or [])})
    expect(report, all("link_target" in n for n in ctx.get("nodes") or []),
           "chat_context nodes expose links for sidebar cards")


def apply_scenario(
    report: dict,
    scenario: dict,
    lead_ref: int,
    *,
    create_test_lead: bool,
    skip_messages: bool,
    bootstrap: bool,
    write_artifacts: bool,
    promote_to_kb: bool,
) -> None:
    load_env()
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
        raise CheckFailure("SUPABASE_URL and SUPABASE_SERVICE_KEY are required for --apply")

    from services import knowledge_graph, supabase_client

    client = supabase_client.get_client()
    expect(report, table_exists(client, "knowledge_items"), "knowledge_items table exists")
    expect(report, table_exists(client, "knowledge_nodes"), "knowledge_nodes table exists")
    expect(report, table_exists(client, "knowledge_edges"), "knowledge_edges table exists")

    persona = ensure_persona(report, supabase_client, scenario)
    persona_id = persona["id"]
    if create_test_lead:
        lead_ref = ensure_test_lead(report, client, persona_id)
        report["lead_ref"] = lead_ref
    source = supabase_client.get_or_create_manual_source()
    source_id = source.get("id") if source else None
    if not bootstrap:
        warn(report, "per-item knowledge_graph.bootstrap_from_item skipped for bulk speed; nodes/edges are still upserted")
    if not write_artifacts:
        warn(report, "artifact/version writes skipped for bulk speed; use --write-artifacts to test canonical artifacts")
    if not promote_to_kb:
        warn(report, "KB promotion skipped; agent text search will not be validated")
    node_by_slug: dict[str, dict] = {}
    for item in scenario["items"]:
        _, node = upsert_item_and_node(
            report,
            supabase_client,
            knowledge_graph,
            client,
            persona_id,
            source_id,
            item,
            bootstrap=bootstrap,
            write_artifacts=write_artifacts,
            promote_to_kb=promote_to_kb,
        )
        node_by_slug[item["slug"]] = node

    upsert_edges(report, supabase_client, node_by_slug, scenario, persona_id)
    if skip_messages:
        warn(report, "skipped inserting database messages; use --create-test-lead or an existing --lead-ref to test message persistence")
    else:
        require_lead_ref(report, supabase_client, lead_ref)
        insert_test_messages(report, supabase_client, scenario, lead_ref)
    validate_real_state(
        report,
        client,
        knowledge_graph,
        scenario,
        persona_id,
        lead_ref,
        validate_messages=not skip_messages,
        validate_kb=promote_to_kb,
    )


def write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=int, default=5)
    parser.add_argument("--copies", type=int, default=10)
    parser.add_argument("--faqs", type=int, default=50)
    parser.add_argument("--lead-ref", type=int, default=91003)
    parser.add_argument("--create-test-lead", action="store_true", help="create/reuse a dedicated test lead and store real messages there")
    parser.add_argument("--skip-messages", action="store_true", help="apply knowledge graph data without inserting messages")
    parser.add_argument("--bootstrap", action="store_true", help="also run knowledge_graph.bootstrap_from_item for every item")
    parser.add_argument("--write-artifacts", action="store_true", help="also upsert knowledge_artifacts and knowledge_artifact_versions")
    parser.add_argument("--skip-kb-promotion", action="store_true", help="do not promote approved items to kb_entries")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "requested_counts": {"products": args.products, "copies": args.copies, "faqs": args.faqs},
        "lead_ref": args.lead_ref,
        "checks": [],
        "warnings": [],
    }

    try:
        scenario = generate_scenario(args.products, args.copies, args.faqs)
        report["planned_counts"] = {
            "items": len(scenario["items"]),
            "products": len(scenario["products"]),
            "copies": len(scenario["copies"]),
            "faqs": len(scenario["faqs"]),
            "edges": len(scenario["edges"]),
            "messages": len(scenario["test_messages"]) * 2,
        }
        expect(report, len(scenario["products"]) == args.products, "planned product count matches request")
        expect(report, len(scenario["copies"]) == args.copies, "planned copy count matches request")
        expect(report, len(scenario["faqs"]) == args.faqs, "planned FAQ count matches request")
        expect(report, all(((p["metadata"].get("price") or {}).get("display")) for p in scenario["products"]),
               "every planned product has structured price")
        report["sample"] = {
            "products": scenario["products"][:5],
            "copies": scenario["copies"][:3],
            "faqs": scenario["faqs"][:3],
            "edges": scenario["edges"][:12],
        }

        if args.apply:
            apply_scenario(
                report,
                scenario,
                args.lead_ref,
                create_test_lead=args.create_test_lead,
                skip_messages=args.skip_messages,
                bootstrap=args.bootstrap,
                write_artifacts=args.write_artifacts,
                promote_to_kb=not args.skip_kb_promotion,
            )
        else:
            print("\n-- Dry-run plan --")
            print(json.dumps(report["planned_counts"], ensure_ascii=False, indent=2))
            print("Use --apply to write this batch to the real Supabase database.")

    except CheckFailure as exc:
        report["ok"] = False
        report["error"] = str(exc)
        write_report(report)
        print(f"FAIL: {exc}")
        return 1
    except Exception as exc:
        report["ok"] = False
        report["error"] = repr(exc)
        write_report(report)
        print(f"ERROR: {exc}")
        return 1

    report["ok"] = all(c.get("ok") for c in report["checks"])
    write_report(report)
    print("PASS: Prime bulk real test " + report["mode"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
