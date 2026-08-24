"""Generate Tock Fatal's denormalized conversational FAQ projection.

Authorship stays top-down. Runtime receives only approved FAQ chunks and never
reconstructs Product -> Offer -> Copy relationships during a conversation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = (
    ROOT / "data" / "graph_bundles" / "tock-fatal"
    / "sdr-qualification-v10-full-catalog.json"
)
GENERATOR = "tock_conversation_faqs_v1"


def _source(node: dict[str, Any]) -> str:
    return str((node.get("data") or {}).get("source") or "pending_source")


def _money(amount: Any) -> str:
    return f"R$ {float(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _faq(
    *, faq_id: str, slug: str, title: str, question: str, aliases: list[str],
    answer: str, source_node: dict[str, Any], branch_path: list[str],
    sources: list[dict[str, str]], claim_type: str, channel: str, approved: bool,
) -> dict[str, Any]:
    status = "approved" if approved else "pending_validation"
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
            "claims": [{
                "claim_type": claim_type,
                "policy": "published_accumulated_faq",
                "evidence_node_ids": [faq_id],
            }],
        },
    }


def generate(bundle: dict[str, Any], *, approved: bool) -> dict[str, Any]:
    nodes = [
        node for node in bundle.get("nodes") or []
        if ((node.get("data") or {}).get("metadata") or {}).get("generator") != GENERATOR
    ]
    generated_ids = {
        str(node.get("id") or "") for node in bundle.get("nodes") or []
        if ((node.get("data") or {}).get("metadata") or {}).get("generator") == GENERATOR
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
        minimum = int(offer_data.get("min_quantity") or 1)
        channel_label = "varejo" if channel == "varejo" else "atacado"
        quantity_text = (
            "A compra é unitária."
            if channel == "varejo"
            else f"A condição vale a partir de {minimum} peças no pedido, que podem ser iguais ou diferentes entre si."
        )
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
        variants = [
            (
                "descricao-indicacao", "Descrição e indicação",
                f"Como é o {product_title} e para quem ele é indicado?",
                [
                    f"me fala sobre o {product_title}",
                    f"como é esse {product_title}",
                    f"para quem serve o {product_title}",
                    f"o {product_title} combina com qual ocasião",
                    f"vale a pena conhecer o {product_title}",
                ],
                f"{product_summary} {copy_summary}".strip(), "service_detail",
            ),
            (
                "preco-canal-quantidade", "Preço, canal e quantidade",
                f"Qual é o preço do {product_title} no {channel_label}?",
                [
                    f"quanto custa o {product_title}",
                    f"preço do {product_title} no {channel_label}",
                    f"qual a quantidade mínima do {product_title}",
                    f"esse valor é atacado ou varejo para {product_title}",
                    f"posso comprar quantas peças de {product_title}",
                ],
                f"No {channel_label}, o {product_title} custa {price}. {quantity_text} {offer_summary}".strip(),
                "price",
            ),
            (
                "recomendacao-comparacao", "Recomendação, comparação e objeção",
                f"O {product_title} é uma boa opção ou devo comparar com outro produto?",
                [
                    f"você recomenda o {product_title}",
                    f"qual a vantagem do {product_title}",
                    f"estou em dúvida sobre o {product_title}",
                    f"tem opção parecida com o {product_title}",
                    f"o {product_title} faz sentido para mim",
                ],
                (
                    f"O {product_title} pertence ao grupo {group_title}. {product_summary} "
                    f"{copy_summary} A comparação ideal depende do estilo, da ocasião ou do objetivo informado pelo cliente."
                ).strip(),
                "service_detail",
            ),
            (
                "duvida-indireta-proxima-acao", "Dúvida indireta e próxima ação",
                f"Estou procurando algo em {group_title}; o {product_title} pode fazer sentido?",
                [
                    f"quero algo de {group_title}",
                    f"procuro uma peça como o {product_title}",
                    f"não sei qual produto escolher em {group_title}",
                    f"o que você sugere em {group_title}",
                    f"quero ver opções parecidas com {product_title}",
                ],
                (
                    f"O {product_title} é uma opção do grupo {group_title}. {product_summary} "
                    f"{copy_summary} A próxima recomendação pode ser refinada pelo uso, estilo, ocasião ou canal de compra que o cliente informar."
                ).strip(),
                "service_detail",
            ),
        ]
        for suffix, label, question, aliases, answer, claim_type in variants:
            faq_id = f"faq:tock-{stem}-{suffix}"
            faq = _faq(
                faq_id=faq_id,
                slug=f"{stem}-{suffix}",
                title=f"{label} — {product_title} ({channel_label})",
                question=question,
                aliases=aliases,
                answer=answer,
                source_node=copy,
                branch_path=[*base_path, faq_id],
                sources=sources,
                claim_type=claim_type,
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
        claim_type="service_detail",
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
