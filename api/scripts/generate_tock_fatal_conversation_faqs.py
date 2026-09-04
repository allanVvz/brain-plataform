"""Generate Tock Fatal's denormalized conversational FAQ projection.

Authorship stays top-down. Runtime receives only approved FAQ chunks and never
reconstructs Product -> Offer -> Copy relationships during a conversation.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = (
    ROOT / "data" / "graph_bundles" / "tock-fatal"
    / "sdr-qualification-v10-full-catalog.json"
)
GENERATOR = "tock_conversation_faqs_v2"
LEGACY_GENERATORS = {"tock_conversation_faqs_v1", GENERATOR}


def _source(node: dict[str, Any]) -> str:
    return str((node.get("data") or {}).get("source") or "pending_source")


def _money(amount: Any) -> str:
    return f"R$ {float(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _semantic_fold(value: str) -> str:
    return " ".join(
        "".join(
            char for char in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(char)
        ).lower().split()
    )


def _copy_without_quantity_policy(value: str) -> str:
    """Keep persuasive copy while removing channel-wide quantity policy."""
    quantity_terms = (
        "pedido minimo",
        "quantidade minima",
        "a partir de 3 pecas",
        "minimo de 3 pecas",
        "compra unitaria",
    )
    sentences = re.split(r"(?<=[.!?])\s+", str(value or "").strip())
    return " ".join(
        sentence for sentence in sentences
        if sentence and not any(term in _semantic_fold(sentence) for term in quantity_terms)
    ).strip()


def _generated_by_this_projection(node: dict[str, Any]) -> bool:
    generator = ((node.get("data") or {}).get("metadata") or {}).get("generator")
    return generator in LEGACY_GENERATORS


def _faq(
    *, faq_id: str, slug: str, title: str, question: str, aliases: list[str],
    answer: str, source_node: dict[str, Any], branch_path: list[str],
    sources: list[dict[str, str]], claim_types: str | list[str], channel: str,
    approved: bool,
) -> dict[str, Any]:
    status = "approved" if approved else "pending_validation"
    normalized_claim_types = (
        [claim_types] if isinstance(claim_types, str) else list(claim_types)
    )
    return {
        "id": faq_id,
        "node_type": "faq",
        "slug": slug,
        "title": title,
        "summary": answer,
        "status": status,
        "data": {
            "question": question,
            "question_aliases": list(dict.fromkeys(aliases)),
            "answer": answer,
            "source_node_id": source_node["id"],
            "source_node_type": source_node["node_type"],
            "branch_path": branch_path,
            "sources": sources,
            "channel": channel,
            "source": "+".join(dict.fromkeys(item["source"] for item in sources)),
            "status": status,
            "metadata": {
                "role": "knowledge_faq",
                "generator": GENERATOR,
                "accumulated_at_publication": True,
            },
            "claims": [
                {
                    "claim_type": claim_type,
                    "policy": "published_accumulated_faq",
                    "evidence_node_ids": [faq_id],
                }
                for claim_type in normalized_claim_types
            ],
        },
    }


def generate(bundle: dict[str, Any], *, approved: bool) -> dict[str, Any]:
    nodes = [
        node for node in bundle.get("nodes") or []
        if not _generated_by_this_projection(node)
    ]
    generated_ids = {
        str(node.get("id") or "") for node in bundle.get("nodes") or []
        if _generated_by_this_projection(node)
    }
    edges = [
        edge for edge in bundle.get("edges") or []
        if edge.get("source") not in generated_ids
        and edge.get("target") not in generated_ids
        and ((edge.get("metadata") or {}).get("generator") != GENERATOR)
    ]
    by_id = {str(node["id"]): node for node in nodes}
    embedded = next(node for node in nodes if node.get("node_type") in {"embed", "embedded"})

    about_product: dict[str, str] = {}
    group_by_product: dict[str, str] = {}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if edge.get("relation_type") == "about_product":
            about_product[source] = target
        if (
            edge.get("relation_type") == "contains"
            and (by_id.get(source) or {}).get("node_type") == "product_group"
            and (by_id.get(target) or {}).get("node_type") == "product"
        ):
            group_by_product[target] = source

    offers: dict[tuple[str, str], dict[str, Any]] = {}
    for node in nodes:
        if node.get("node_type") != "offer":
            continue
        product_id = about_product.get(str(node["id"]))
        channel = str((node.get("data") or {}).get("channel") or "")
        if product_id and channel:
            offers[(product_id, channel)] = node

    generated: list[dict[str, Any]] = []
    generated_edges: list[dict[str, Any]] = []
    persona_id = "persona:tock-fatal"
    campaign_id = "campaign:tock-catalogo-produtos"

    for copy in sorted(
        (node for node in nodes if node.get("node_type") == "copy"),
        key=lambda item: str(item.get("id") or ""),
    ):
        copy_id = str(copy["id"])
        product_id = about_product.get(copy_id)
        channel = str((copy.get("data") or {}).get("channel") or "")
        product = by_id.get(str(product_id)) or {}
        offer = offers.get((str(product_id), channel)) or {}
        group = by_id.get(group_by_product.get(str(product_id), "")) or {}
        if not product or not offer or not group or channel not in {"varejo", "atacado"}:
            raise ValueError(f"copy branch incomplete: {copy_id}")

        audience_id = "audience:tock-retail" if channel == "varejo" else "audience:tock-reseller"
        brand_id = "brand:tock-fatal-varejo" if channel == "varejo" else "brand:tock-fatal-atacado"
        product_title = str(product.get("title") or product.get("slug"))
        group_title = str(group.get("title") or group.get("slug"))
        product_summary = str(product.get("summary") or (product.get("data") or {}).get("description") or "").strip()
        copy_summary = str(copy.get("summary") or "").strip()
        offer_data = offer.get("data") or {}
        offer_summary = str(offer.get("summary") or "").strip()
        price = _money((offer_data.get("price") or {}).get("amount"))
        channel_label = "varejo" if channel == "varejo" else "atacado"
        commercial_copy = _copy_without_quantity_policy(copy_summary)
        commercial_offer = _copy_without_quantity_policy(offer_summary)
        sources = [
            {"node_id": str(group["id"]), "source": _source(group)},
            {"node_id": str(product["id"]), "source": _source(product)},
            {"node_id": str(offer["id"]), "source": _source(offer)},
            {"node_id": copy_id, "source": _source(copy)},
        ]
        base_path = [
            persona_id, brand_id, campaign_id, audience_id, str(group["id"]),
            str(product["id"]), str(offer["id"]), copy_id,
        ]
        stem = str(copy.get("slug") or copy_id.replace(":", "-"))
        faq_id = f"faq:tock-{stem}-produto-canal"
        aliases = [
            f"me fala sobre o {product_title}",
            f"como é esse {product_title}",
            f"para quem serve o {product_title}",
            f"o {product_title} combina com qual ocasião",
            f"vale a pena conhecer o {product_title}",
            f"quanto custa o {product_title}",
            f"preço do {product_title} no {channel_label}",
            f"esse valor é atacado ou varejo para {product_title}",
            f"você recomenda o {product_title}",
            f"qual a vantagem do {product_title}",
            f"estou em dúvida sobre o {product_title}",
            f"tem opção parecida com o {product_title}",
            f"o {product_title} faz sentido para mim",
            f"quero algo de {group_title}",
            f"procuro uma peça como o {product_title}",
            f"não sei qual produto escolher em {group_title}",
            f"o que você sugere em {group_title}",
            f"quero ver opções parecidas com {product_title}",
        ]
        answer = (
            f"O {product_title} pertence ao grupo {group_title}. {product_summary} "
            f"{commercial_copy} No {channel_label}, custa {price}. {commercial_offer} "
            "A recomendação pode ser refinada pelo estilo, ocasião ou objetivo informado pelo cliente."
        ).strip()
        faq = _faq(
            faq_id=faq_id,
            slug=f"{stem}-produto-canal",
            title=f"Produto e preço — {product_title} ({channel_label})",
            question=f"Como é e quanto custa o {product_title} no {channel_label}?",
            aliases=aliases,
            answer=answer,
            source_node=copy,
            branch_path=[*base_path, faq_id],
            sources=sources,
            claim_types=["service_detail", "price"],
            channel=channel,
            approved=approved,
        )
        generated.append(faq)
        generated_edges.extend([
            {
                "id": f"edge:contains:{copy_id}:{faq_id}",
                "source": copy_id,
                "target": faq_id,
                "relation_type": "contains",
                "metadata": {"generator": GENERATOR},
            },
            {
                "id": f"edge:publishes:{faq_id}:{embedded['id']}",
                "source": faq_id,
                "target": embedded["id"],
                "relation_type": "publishes_to",
                "metadata": {"generator": GENERATOR},
            },
        ])

    quantity_policies = [
        {
            "faq_id": "faq:tock-retail-minimum-quantity",
            "audience_id": "audience:tock-retail",
            "channel": "varejo",
            "title": "Quantidade mínima — varejo",
            "question": "Qual é a quantidade mínima para comprar no varejo?",
            "aliases": [
                "qual é o pedido mínimo no varejo",
                "posso comprar uma peça",
                "quantas peças preciso comprar para uso próprio",
            ],
            "answer": "No varejo, a compra mínima é de 1 peça.",
            "sources": [
                {
                    "node_id": "audience:tock-retail",
                    "source": "user_instruction_2026-08-25",
                },
            ],
        },
        {
            "faq_id": "faq:tock-reseller-minimum-quantity",
            "audience_id": "audience:tock-reseller",
            "channel": "atacado",
            "title": "Quantidade mínima — atacado",
            "question": "Qual é a quantidade mínima para comprar no atacado?",
            "aliases": [
                "qual é o pedido mínimo no atacado",
                "quantas peças preciso comprar para revenda",
                "posso misturar peças no pedido mínimo",
            ],
            "answer": "No atacado, o pedido mínimo é de 3 peças, iguais ou diferentes entre si.",
            "sources": [
                {
                    "node_id": "audience:tock-reseller",
                    "source": "user_instruction_2026-08-25",
                },
                {
                    "node_id": "rule:tock-desconto-atacado-30",
                    "source": _source(by_id["rule:tock-desconto-atacado-30"]),
                },
            ],
        },
    ]
    qualification_campaign_id = "campaign:tock-whatsapp-qualification"
    for policy in quantity_policies:
        audience = by_id[policy["audience_id"]]
        faq_id = policy["faq_id"]
        faq = _faq(
            faq_id=faq_id,
            slug=faq_id.removeprefix("faq:tock-"),
            title=policy["title"],
            question=policy["question"],
            aliases=policy["aliases"],
            answer=policy["answer"],
            source_node=audience,
            branch_path=[
                persona_id, qualification_campaign_id, policy["audience_id"], faq_id,
            ],
            sources=policy["sources"],
            claim_types="minimum_order",
            channel=policy["channel"],
            approved=approved,
        )
        generated.append(faq)
        generated_edges.extend([
            {
                "id": f"edge:contains:{policy['audience_id']}:{faq_id}",
                "source": policy["audience_id"],
                "target": faq_id,
                "relation_type": "contains",
                "metadata": {"generator": GENERATOR},
            },
            {
                "id": f"edge:publishes:{faq_id}:{embedded['id']}",
                "source": faq_id,
                "target": embedded["id"],
                "relation_type": "publishes_to",
                "metadata": {"generator": GENERATOR},
            },
        ])

    groups = sorted(
        (node for node in nodes if node.get("node_type") == "product_group"),
        key=lambda item: str(item.get("title") or ""),
    )
    group_names = [str(group.get("title") or group.get("slug")) for group in groups]
    overview_id = "faq:tock-catalogo-grupos"
    overview_source = by_id[campaign_id]
    overview = _faq(
        faq_id=overview_id,
        slug="catalogo-grupos",
        title="Grupos de produtos do catálogo",
        question="Quais grupos de produtos vocês têm?",
        aliases=[
            "quais opções vocês têm", "o que vocês vendem", "me mostra o catálogo",
            "quais categorias estão disponíveis", "que tipos de roupa vocês trabalham",
        ],
        answer="O catálogo está organizado nestes grupos: " + ", ".join(group_names) + ".",
        source_node=overview_source,
        branch_path=[persona_id, campaign_id, overview_id],
        sources=[{"node_id": campaign_id, "source": _source(overview_source)}],
        claim_types="service_detail",
        channel="all",
        approved=approved,
    )
    generated.append(overview)
    generated_edges.extend([
        {
            "id": f"edge:contains:{campaign_id}:{overview_id}",
            "source": campaign_id,
            "target": overview_id,
            "relation_type": "contains",
            "metadata": {"generator": GENERATOR},
        },
        {
            "id": f"edge:publishes:{overview_id}:{embedded['id']}",
            "source": overview_id,
            "target": embedded["id"],
            "relation_type": "publishes_to",
            "metadata": {"generator": GENERATOR},
        },
    ])

    # One channel-neutral navigation FAQ per published ProductGroup gives the
    # vector search a self-contained catalog answer before a channel-specific
    # Offer is known. Prices and commercial conditions stay exclusively in the
    # descendant Offer/Copy FAQs, so retail and wholesale never mix here.
    products_by_group: dict[str, list[dict[str, Any]]] = {}
    for product_id, group_id in group_by_product.items():
        product = by_id.get(product_id)
        if product:
            products_by_group.setdefault(group_id, []).append(product)
    for group in groups:
        group_id = str(group["id"])
        group_title = str(group.get("title") or group.get("slug"))
        products = sorted(
            products_by_group.get(group_id) or [],
            key=lambda item: str(item.get("title") or ""),
        )
        if not products:
            continue
        product_titles = [
            str(product.get("title") or product.get("slug")) for product in products
        ]
        stem = str(group.get("slug") or group_id.replace(":", "-"))
        faq_id = f"faq:tock-{stem}-navegacao"
        aliases = [
            f"quais produtos têm em {group_title}",
            f"quero ver {group_title}",
            f"me mostra as opções de {group_title}",
            f"o que vocês têm de {group_title}",
            *[
                f"quero algo tipo {title}"
                for title in product_titles[:8]
            ],
        ]
        sources = [
            {"node_id": group_id, "source": _source(group)},
            *[
                {"node_id": str(product["id"]), "source": _source(product)}
                for product in products
            ],
        ]
        faq = _faq(
            faq_id=faq_id,
            slug=f"{stem}-navegacao",
            title=f"Navegação consultiva — {group_title}",
            question=f"Quais produtos vocês têm em {group_title}?",
            aliases=aliases,
            answer=(
                f"No grupo {group_title}, as opções publicadas são: "
                + ", ".join(product_titles)
                + ". A recomendação pode ser refinada pelo estilo, ocasião ou objetivo que o cliente informar."
            ),
            source_node=group,
            branch_path=[persona_id, campaign_id, group_id, faq_id],
            sources=sources,
            claim_types="service_detail",
            channel="all",
            approved=approved,
        )
        generated.append(faq)
        generated_edges.extend([
            {
                "id": f"edge:contains:{group_id}:{faq_id}",
                "source": group_id,
                "target": faq_id,
                "relation_type": "contains",
                "metadata": {"generator": GENERATOR},
            },
            {
                "id": f"edge:publishes:{faq_id}:{embedded['id']}",
                "source": faq_id,
                "target": embedded["id"],
                "relation_type": "publishes_to",
                "metadata": {"generator": GENERATOR},
            },
        ])

    result = {**bundle, "nodes": [*nodes, *generated], "edges": [*edges, *generated_edges]}
    if approved:
        for node in result["nodes"]:
            if node.get("node_type") != "faq":
                continue
            node["status"] = "approved"
            node["data"] = {**dict(node.get("data") or {}), "status": "approved"}

    faq_status = {
        str(node["id"]): str(node.get("status") or "")
        for node in result["nodes"]
        if node.get("node_type") == "faq"
    }
    embedded_id = str(embedded["id"])
    canonical_edges: list[dict[str, Any]] = []
    projected_faqs: set[str] = set()
    for edge in result["edges"]:
        source = str(edge.get("source") or "")
        is_faq_projection = (
            edge.get("relation_type") == "publishes_to"
            and source in faq_status
            and str(edge.get("target") or "") == embedded_id
        )
        if not is_faq_projection:
            canonical_edges.append(edge)
            continue
        if faq_status[source] != "approved" or source in projected_faqs:
            continue
        canonical_edges.append(edge)
        projected_faqs.add(source)
    for faq_id in sorted(
        node_id for node_id, status in faq_status.items() if status == "approved"
    ):
        if faq_id in projected_faqs:
            continue
        canonical_edges.append({
            "id": f"edge:publishes:{faq_id}:{embedded_id}",
            "source": faq_id,
            "target": embedded_id,
            "relation_type": "publishes_to",
            "metadata": {"generator": GENERATOR, "canonical_projection": True},
        })
        projected_faqs.add(faq_id)
    result["edges"] = canonical_edges
    result["metadata"] = {
        **dict(bundle.get("metadata") or {}),
        "conversation_faq_generator": GENERATOR,
        "conversation_faq_count": len(generated),
        "conversation_faq_status": "approved" if approved else "pending_validation",
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    generated = generate(bundle, approved=args.approve)
    args.bundle.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "bundle": str(args.bundle),
        "generated_faqs": generated["metadata"]["conversation_faq_count"],
        "status": generated["metadata"]["conversation_faq_status"],
        "nodes": len(generated["nodes"]),
        "edges": len(generated["edges"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
