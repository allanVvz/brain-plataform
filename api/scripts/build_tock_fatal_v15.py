"""Build the Tock Fatal v15 GraphBundle: FAQs that steer the conversation.

The v14 bundle made the commercial branch stable. This one gives the retrieval
layer the material to *move* a conversation instead of only answering it.

## What was missing

Measured against the v14 bundle (606 FAQs):

| gap | cobertura antes |
|---|---|
| cliente chega pelo site | 0 |
| "quero mais peças" (o gatilho de atacado) | 0 |
| item que não existe no catálogo | 0 |
| mínimo de atacado como momento de fluxo | 292, todas por produto, nenhuma no galho de varejo |

The 292 hits all sit inside per-product wholesale FAQs, so a retail customer
asking "e se eu levar 3?" had nothing covered to receive -- the branch that owns
the trigger could not talk about the trigger.

## What this adds

Five FAQs, placed so each one is reachable exactly where it belongs:

- retail and wholesale entry FAQs, one per branch, for the customer who arrives
  from that brand's public page;
- the wholesale doorway, in the **retail** branch: the only retail FAQ allowed to
  mention the wholesale condition, and it names the rule without quoting a
  wholesale price;
- the minimum, in the wholesale branch, as a flow moment rather than a per-product
  detail;
- "we don't carry that", as global context, so an honest refusal is graph-owned
  instead of improvised.

## What this changes

The seven group-navigation FAQs ended with *"A recomendação pode ser refinada
pelo estilo, ocasião ou objetivo que o cliente informar."* -- that describes the
agent's capability to a reader of the graph; it is not something you say to a
customer. Replaced with an actual question, which is what makes the turn move.

Product names, prices, offers and every commercial claim stay byte-stable.

    python api/scripts/build_tock_fatal_v15.py <source> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

BASELINE_PURPOSE = "tock_fatal_v14_branch_stability"

RETAIL = "audience:tock-retail"
RESELLER = "audience:tock-reseller"
CAMPAIGN = "campaign:tock-catalogo-produtos"
EMBED_ID = "embed:tock-default"
DISCOUNT_RULE = "rule:tock-desconto-atacado-30"
BRIEFING = "briefing:tock-catalogo-instrucoes"

SOURCE_TAG = "flow_direction_faqs_2026-09-04"

# The meta-instruction that leaked into seven customer-facing answers.
NAV_TAIL = (
    "A recomendação pode ser refinada pelo estilo, ocasião ou objetivo que o "
    "cliente informar."
)
NAV_TAIL_REPLACEMENT = "Qual desses combina com o que você procura?"


def _faq(
    node_id: str,
    *,
    slug: str,
    title: str,
    question: str,
    answer: str,
    aliases: list[str],
    channel: str | None = None,
    claim_type: str = "service_detail",
    global_context: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "question": question,
        "question_aliases": aliases,
        "answer": answer,
        "source": SOURCE_TAG,
        "status": "approved",
    }
    if channel:
        data["channel"] = channel
    # Every factual FAQ carries exactly one self-referential claim: the
    # compiler requires `evidence_node_ids == [own id]`, because under
    # `published_accumulated_faq` the published FAQ *is* the evidence. Citing
    # another node is rejected, and citing one from the other branch is
    # rejected twice over (`commercial_claim_evidence_outside_scope`).
    if answer.strip():
        data["claims"] = [{
            "claim_type": claim_type,
            "policy": "published_accumulated_faq",
            "evidence_node_ids": [node_id],
        }]
    if global_context:
        data["capabilities"] = {"global_context": True}
    return {
        "id": node_id,
        "node_type": "faq",
        "slug": slug,
        "title": title,
        "summary": answer,
        "tags": ["fluxo", "direcionamento"],
        "status": "approved",
        "data": data,
    }


def _new_faqs() -> list[tuple[str, dict[str, Any]]]:
    """(parent_node_id, faq) pairs. The parent decides which branch sees it."""
    return [
        (
            RETAIL,
            _faq(
                "faq:tock-varejo-entrada-site",
                slug="varejo-entrada-site",
                title="Cliente chega pelo site — varejo",
                question="Vim pelo site, o que vocês têm?",
                aliases=[
                    "vim pelo site", "cheguei pelo site", "vi no site",
                    "vim da landing", "quero ver as peças do site",
                ],
                answer=(
                    "Que bom que você veio! O catálogo é organizado por grupo: "
                    "vestidos, conjuntos, blusas e partes de cima, calças e "
                    "partes de baixo, casacos, calçados, e infantil, masculino "
                    "e acessórios. Por qual deles você quer começar?"
                ),
                channel="varejo",
            ),
        ),
        (
            RESELLER,
            _faq(
                "faq:tock-atacado-entrada-site",
                slug="atacado-entrada-site",
                title="Cliente chega pelo site — atacado",
                question="Vim pelo site e quero comprar para revender.",
                aliases=[
                    "vim pelo site para revenda", "cheguei pelo site quero revender",
                    "vi no site quero atacado", "quero montar mix",
                ],
                answer=(
                    "Perfeito! Trabalhamos com mix livre entre categorias, então "
                    "você pode montar o pedido com peças diferentes. O catálogo "
                    "tem vestidos, conjuntos, blusas, calças, casacos, calçados e "
                    "infantil, masculino e acessórios. Quer começar pelo que mais "
                    "gira ou já tem um grupo em mente?"
                ),
                channel="atacado",
            ),
        ),
        (
            # The wholesale doorway lives in RETAIL on purpose: this is the one
            # trigger that legitimately moves a customer between branches, and
            # the branch that receives the request has to be able to answer it.
            # It names the quantity that opens the door -- that is the journey
            # rule, not a price -- and deliberately quotes no wholesale figure.
            # The terms belong to the wholesale branch, after the switch.
            RETAIL,
            _faq(
                "faq:tock-varejo-mais-pecas",
                slug="varejo-mais-pecas",
                title="Cliente de varejo pede mais peças",
                question="E se eu levar mais peças?",
                aliases=[
                    "quero mais peças", "e se eu levar 3", "se eu levar mais",
                    "tem desconto por quantidade", "comprando mais fica melhor",
                    "quero levar várias", "desconto para mais peças",
                ],
                answer=(
                    "A partir de 3 peças no mesmo pedido, iguais ou diferentes "
                    "entre si, dá pra te atender na condição de atacado. Quer "
                    "que eu troque e te mostre como fica?"
                ),
                channel="varejo",
            ),
        ),
        (
            RESELLER,
            _faq(
                "faq:tock-atacado-minimo",
                slug="atacado-minimo",
                title="Mínimo e desconto de atacado",
                question="Qual é o mínimo para comprar no atacado?",
                aliases=[
                    "qual o mínimo", "pedido mínimo", "quantas peças no mínimo",
                    "como funciona o desconto", "preciso levar quantas",
                ],
                answer=(
                    "São 3 peças no mesmo pedido, e elas podem ser diferentes "
                    "entre si — vale qualquer combinação do catálogo. A partir "
                    "daí cada peça sai com 30% de desconto sobre o preço de "
                    "varejo. Quer montar o mix agora?"
                ),
                channel="atacado",
                claim_type="price",
            ),
        ),
        (
            # Global context: an honest refusal must be graph-owned, not
            # improvised. It also keeps the redirect inside the catalogue.
            CAMPAIGN,
            _faq(
                "faq:tock-item-inexistente",
                slug="item-inexistente",
                title="Item fora do catálogo",
                question="Vocês têm uma peça que não está no catálogo?",
                aliases=[
                    "vocês têm colete", "tem calçado infantil", "vocês vendem bolsa",
                    "tem esse modelo", "não achei o que procuro",
                ],
                answer=(
                    "Essa peça não está no catálogo atual. O que temos hoje é "
                    "vestidos, conjuntos, blusas e partes de cima, calças e "
                    "partes de baixo, casacos e sobreposições, calçados, e "
                    "infantil, masculino e acessórios. Quer que eu te mostre "
                    "algo parecido com o que você procurava?"
                ),
                global_context=True,
            ),
        ),
    ]


def _assert_baseline(bundle: dict[str, Any]) -> None:
    metadata = bundle.get("metadata") or {}
    if (bundle.get("persona") or {}).get("slug") != "tock-fatal":
        raise ValueError("the baseline is not the Tock Fatal bundle")
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(
            f"expected the {BASELINE_PURPOSE} baseline, got {metadata.get('purpose')!r}"
        )
    existing = {node["id"] for node in bundle["nodes"]}
    for parent, faq in _new_faqs():
        if faq["id"] in existing:
            raise ValueError(f"baseline already carries {faq['id']}")
        if parent not in existing:
            raise ValueError(f"baseline is missing the parent {parent}")
    if DISCOUNT_RULE not in existing:
        raise ValueError(f"baseline is missing the evidence node {DISCOUNT_RULE}")


def build(source: dict[str, Any]) -> dict[str, Any]:
    _assert_baseline(source)
    candidate = copy.deepcopy(source)

    # 1. the meta-instruction that was talking about the customer instead of to
    #    them, in the seven group-navigation answers
    rewritten = 0
    for node in candidate["nodes"]:
        data = node.get("data") or {}
        if NAV_TAIL not in str(data.get("answer") or ""):
            continue
        data["answer"] = data["answer"].replace(NAV_TAIL, NAV_TAIL_REPLACEMENT)
        node["summary"] = str(node.get("summary") or "").replace(
            NAV_TAIL, NAV_TAIL_REPLACEMENT
        )
        rewritten += 1

    # 2. the five flow FAQs, each parented into the branch that should see it
    edges = list(candidate["edges"])
    for parent, faq in _new_faqs():
        candidate["nodes"].append(faq)
        edges.append({
            "id": f"edge:tock-{faq['slug']}-parent",
            "source": parent,
            "target": faq["id"],
            "relation_type": "contains",
        })
        edges.append({
            "id": f"edge:tock-{faq['slug']}-embed",
            "source": faq["id"],
            "target": EMBED_ID,
            "relation_type": "publishes_to",
        })
    candidate["edges"] = edges

    candidate["metadata"] = {
        **(candidate.get("metadata") or {}),
        "purpose": "tock_fatal_v15_flow_faqs",
        "content_revision": "3.4-flow-faqs",
        "flow_faq_rewritten_navigation": rewritten,
        "change_summary": (
            "Cinco FAQ de direcionamento (entrada por site em cada marca, "
            "gatilho de atacado no varejo, mínimo no atacado, item inexistente "
            "como contexto global) e reescrita da cauda meta-instrucional das "
            "sete FAQ de navegação por grupo."
        ),
    }
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8"))
    candidate = build(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}")
    print(f"  nodes {len(source['nodes'])} -> {len(candidate['nodes'])}")
    print(f"  edges {len(source['edges'])} -> {len(candidate['edges'])}")
    print(f"  navegação reescrita: {candidate['metadata']['flow_faq_rewritten_navigation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
