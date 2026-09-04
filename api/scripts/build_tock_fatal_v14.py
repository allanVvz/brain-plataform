"""Build the Tock Fatal v14 GraphBundle: a neutral branch selector.

## The defect this fixes

The branch selector field `purchase_profile` is declared in both audiences, as
the compiler requires (`graph_compiler_v3.branch_selection_field_key` only
accepts a selector declared by at least two branches, each owning its own
declaration). But each declaration pointed at its **own** question node:

    audience:tock-retail   contains  faq:tock-retail-profile
    audience:tock-reseller contains  faq:tock-reseller-profile   (identical text)

`_common_persona_contract` builds the shared contract from `anchors[0]`, and the
anchors are sorted, so `audience:tock-reseller` wins on the alphabet alone
(`res` < `ret`). Every customer -- retail included -- was therefore asked the
**wholesale branch's** question node, which lives inside the wholesale closure.
Production confirmed it (persona tock-fatal, publication v12):

    common_contract.purchase_profile.question_node_id = faq:tock-reseller-profile

The observed consequence, lead 181 on 2026-09-04: the customer arrived from the
retail landing page, answered "uso proprio", and the next question was
`resale_stage` -- "você está começando agora ou já tem loja ou revenda?" -- a
wholesale question asked of a retail customer, with `active_branch_node_id`
still null.

## The fix

One neutral question node, `faq:tock-purchase-profile`, referenced by **both**
declarations. The field stays declared per branch, so the compiler still
recognises the selector; only the question it points at stops belonging to a
brand. The node carries `capabilities.global_context` so it reaches both branch
closures without being a descendant of either -- the same mechanism the tone,
rule and briefing nodes already use.

The two old nodes are archived, never deleted: the active publication still
references them, and a slug that simply disappears is never reconciled.

Nothing else moves. Offers, prices, products, assets and every commercial claim
stay byte-stable.

    python api/scripts/build_tock_fatal_v14.py <source> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

BASELINE_PURPOSE = "tock_fatal_v13_brand_identity"

SELECTOR_FIELD_KEY = "purchase_profile"
NEUTRAL_QUESTION_ID = "faq:tock-purchase-profile"
SELECTOR_PARENT_ID = "campaign:tock-whatsapp-qualification"
EMBED_ID = "embed:tock-default"

# The two brand-owned copies this bundle retires.
LEGACY_QUESTION_IDS = ("faq:tock-retail-profile", "faq:tock-reseller-profile")

BRANCH_ANCHORS = ("audience:tock-retail", "audience:tock-reseller")

# Only these triggers may move a customer between commercial branches. Without
# one, the branch chosen at the start of the journey is immutable: a customer
# who came in as retail must not drift into wholesale discourse or pricing.
BRANCH_STABILITY = {
    "policy": "single_journey_per_customer",
    "description": (
        "O galho comercial escolhido no início da jornada é imutável. "
        "Só os gatilhos declarados abaixo autorizam a troca."
    ),
    "switch_triggers": [
        {
            "id": "customer_requests_more_pieces",
            "kind": "intent",
            "description": "O cliente pede explicitamente mais peças ou volume.",
            "to_branch_node_id": "audience:tock-reseller",
        },
        {
            "id": "order_reaches_wholesale_minimum",
            "kind": "quantity_threshold",
            "description": (
                "O pedido atinge o mínimo de atacado: 3 peças, iguais ou "
                "diferentes entre si."
            ),
            "min_total_quantity": 3,
            "to_branch_node_id": "audience:tock-reseller",
        },
    ],
    "forbidden": (
        "Nenhuma outra evidência troca o galho. Menção casual a revenda, "
        "atacado ou preço não é gatilho."
    ),
}

# A lead that arrives from a brand's own public page already has its branch
# decided; asking the profile question again is noise, and asking it from the
# wrong brand's node is the defect this bundle fixes.
ORIGIN_BRANCH_BINDING = {
    "field_key": SELECTOR_FIELD_KEY,
    "description": (
        "Origem do lead define o galho antes do primeiro turno. O CTA público "
        "carrega o ref; quando ele casa, a pergunta de perfil é pulada."
    ),
    "rules": [
        {"origin_ref_prefix": "cabecalho:tock-fatal", "branch_node_id": "audience:tock-retail",
         "value": "uso-proprio-varejo"},
        {"origin_ref_prefix": "audience:tock-retail", "branch_node_id": "audience:tock-retail",
         "value": "uso-proprio-varejo"},
        {"origin_ref_prefix": "audience:tock-reseller", "branch_node_id": "audience:tock-reseller",
         "value": "atacado-revenda"},
    ],
}


def _node_index(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in bundle["nodes"]}


def _assert_baseline(bundle: dict[str, Any]) -> None:
    metadata = bundle.get("metadata") or {}
    if (bundle.get("persona") or {}).get("slug") != "tock-fatal":
        raise ValueError("the baseline is not the Tock Fatal bundle")
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(
            f"expected the {BASELINE_PURPOSE} baseline, got {metadata.get('purpose')!r}"
        )
    nodes = _node_index(bundle)
    for node_id in LEGACY_QUESTION_IDS:
        if node_id not in nodes:
            raise ValueError(f"baseline is missing the question node {node_id}")
    if NEUTRAL_QUESTION_ID in nodes:
        raise ValueError("the baseline already carries the neutral selector")
    for anchor in BRANCH_ANCHORS:
        if anchor not in nodes:
            raise ValueError(f"baseline is missing the branch anchor {anchor}")


def _neutral_question(source_node: dict[str, Any]) -> dict[str, Any]:
    """The selector question, owned by no brand.

    Text and aliases are copied verbatim from the retired node so retrieval
    behaviour does not shift: this bundle changes *who owns the question*, not
    what it asks.
    """
    data = copy.deepcopy(source_node.get("data") or {})
    data["capabilities"] = {**(data.get("capabilities") or {}), "global_context": True}
    data["source"] = "branch_selector_neutralisation_2026-09-04"
    data["status"] = source_node.get("status") or "approved"
    data["branch_selector"] = {
        "field_key": SELECTOR_FIELD_KEY,
        "description": (
            "Pergunta neutra de seleção de galho. Não pertence a nenhuma marca; "
            "as duas audiences apontam para ela."
        ),
    }
    return {
        "id": NEUTRAL_QUESTION_ID,
        "node_type": "faq",
        "slug": "purchase-profile",
        "title": "Perfil de compra",
        "summary": source_node.get("summary") or "",
        "tags": ["qualificacao", "selecao-de-galho"],
        "status": source_node.get("status") or "validated",
        "data": data,
    }


def _superseded(node: dict[str, Any]) -> dict[str, Any]:
    """Mark a retired question without archiving it inside the bundle.

    `archived` is not a publishable status (`bundle_node_not_publishable`), and
    the publisher has no removal path yet -- a node dropped from the bundle
    simply stops being touched and stays active in the graph, which is the
    orphan-node failure this project has already been bitten by.

    So the node stays exactly where it is, publishable and parented, and only
    stops being referenced: nothing points at it as the selector any more. It
    carries `role: qualification_question`, which the compiler excludes from RAG
    eligibility, so it is unreachable as retrieval content too. Real archival
    waits for the publisher's removal support (roadmap item 1).
    """
    out = copy.deepcopy(node)
    data = out.get("data") or {}
    data["superseded_by"] = NEUTRAL_QUESTION_ID
    data["superseded_at"] = "2026-09-04"
    data["superseded_reason"] = (
        "Uma pergunta de seleção de galho não pode pertencer a uma das marcas "
        "que ela escolhe. Arquivar quando o publisher suportar remoção."
    )
    out["data"] = data
    return out


def build(source: dict[str, Any]) -> dict[str, Any]:
    _assert_baseline(source)
    candidate = copy.deepcopy(source)
    nodes = _node_index(candidate)

    # 1. the neutral question, modelled on the node the compiler was picking
    neutral = _neutral_question(nodes[LEGACY_QUESTION_IDS[1]])

    rebuilt: list[dict[str, Any]] = []
    for node in candidate["nodes"]:
        if node["id"] in LEGACY_QUESTION_IDS:
            rebuilt.append(_superseded(node))
            continue
        rebuilt.append(node)
    rebuilt.append(neutral)

    # 2. both declarations point at the neutral node; ownership stays per branch
    #    so branch_selection_field_key keeps recognising the selector.
    for anchor in BRANCH_ANCHORS:
        node = next(item for item in rebuilt if item["id"] == anchor)
        fields = ((node.get("data") or {}).get("qualification") or {}).get("fields") or []
        for field in fields:
            if field.get("key") == SELECTOR_FIELD_KEY:
                field["question_node_id"] = NEUTRAL_QUESTION_ID

    candidate["nodes"] = rebuilt

    # 3. edges: hang the neutral question under the qualification campaign and
    #    publish it to the embed, mirroring what the retired nodes had. The
    #    retired nodes keep their parents -- every node needs a primary parent
    #    to be publishable, and orphaning them is the failure mode this repo has
    #    already hit. They simply stop being referenced.
    edges = list(candidate["edges"])
    edges.append({
        "id": "edge:tock-campaign-purchase-profile",
        "source": SELECTOR_PARENT_ID,
        "target": NEUTRAL_QUESTION_ID,
        "relation_type": "contains",
    })
    edges.append({
        "id": "edge:tock-purchase-profile-embed",
        "source": NEUTRAL_QUESTION_ID,
        "target": EMBED_ID,
        "relation_type": "publishes_to",
    })
    candidate["edges"] = edges

    # 4. branch stability and origin binding, declared as data on the persona
    persona = next(item for item in candidate["nodes"] if item["node_type"] == "persona")
    policy = persona["data"]["conversation_policy"]
    policy["branch_selection"] = {
        **(policy.get("branch_selection") or {}),
        "field_key": SELECTOR_FIELD_KEY,
        "question_node_id": NEUTRAL_QUESTION_ID,
        "stability": BRANCH_STABILITY,
        "origin_binding": ORIGIN_BRANCH_BINDING,
    }

    candidate["metadata"] = {
        **(candidate.get("metadata") or {}),
        "purpose": "tock_fatal_v14_branch_stability",
        "content_revision": "3.3-branch-stability",
        "baseline_publication": {
            "version": 12,
            "source_bundle": (
                "data/graph_bundles/tock-fatal/sdr-qualification-v13-brand-identity.json"
            ),
        },
        "change_summary": (
            "Seletor de galho neutro: as duas audiences apontam para "
            "faq:tock-purchase-profile. Sem isso o contrato comum herdava a "
            "pergunta do galho de atacado por ordem alfabética dos anchors, e "
            "todo cliente de varejo era qualificado por dentro da marca errada."
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
