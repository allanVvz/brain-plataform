"""Build the Utzig commercial-alignment v15 overlay and candidate bundle.

Source of truth for the commercial data: Luiza Camargo (Utzig), WhatsApp,
2026-09-28. Base: the active v13 publication (draft checksum
sha256:b23cea31...). The SDR never states prices: price facts live only in
offer nodes (used by the public site) and price-only FAQs are rewritten to
duration + "o atendente confirma o valor".

Run from the repository root:
    python data/graph_bundles/utzig-garage/build_commercial_alignment_v15.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "api" / "scripts"))

from prepare_graph_bundle_candidate import apply_overlay  # noqa: E402

BASE_FILE = HERE / "utzig-optional-identity-v13.json"
OVERLAY_FILE = HERE / "utzig-commercial-alignment-v15.overlay.json"
BUNDLE_FILE = HERE / "utzig-commercial-alignment-v15.json"
PENDING_FILE = HERE / "utzig-commercial-alignment-v15.pending-faqs.json"
ACTIVE = {
    "publication_id": "6b85bf7a-ab87-4f3b-a1d1-4a6b4ae4c05f",
    "version": 13,
    "checksum": "sha256:961c06d8fe7e707b3e71c74c2aa1b8c50d6b828436b0b15f2005381dc00a5f32",
}
SOURCE = "luiza_camargo_whatsapp_2026_09_28"
EMBEDDED = "embedded:utzig"
GLOBAL_PARENT = "rule:human-handoff"
REMOVAL_REASON = "servico_descontinuado_pela_utzig_2026_09_28"
# v15a (default) keeps the discontinued services in the graph and only takes
# them off the site; v15b (UTZIG_V15_RETIRE=1) archives them once the publish
# workflow runs apply_graph_node_retirements.py.
RETIRE_NODES = os.environ.get("UTZIG_V15_RETIRE", "1") == "1"
MONEY = re.compile(r"R\$\s?\d|\d+,\d{2}\b")
SENTENCE = re.compile(r"(?<=[.!?])\s+")

# Services Utzig no longer offers (LP and SDR).
RETIRED_ROOTS = [
    "product:bodywork", "product:painting", "product:vehicle-wrap",
    "product:window-film", "group:repair-paint",
]
RETIRED_EXTRA = [
    "faq:site:window-film-benefit", "copy:site-faq:window-film-benefit",
    "faq:qualification:vehicle_color", "asset:repair-paint-representative-v1",
]

SECTOR_TITLES = {
    "group:cleaning": "Limpeza e higienização",
    "group:revitalization": "Brilho e correção",
    "group:enhancement": "Proteção",
    "group:preservation": "Avaliação e orientação",
}
PRODUCT_TITLES = {
    "product:detailed-wash": "Lavagem detalhada",
    "product:chassis-wash": "Lavagem de chassi",
    "product:engine-bay-wash": "Lavagem de motor",
    "product:vitrification": "Vitrificação da pintura",
    "product:seat-vitrification": "Vitrificação de plásticos e couros",
    "product:windshield-crystallization": "Cristalização do para-brisa",
    "product:headlight-restoration": "Restauração de faróis",
}

# (product, amount, qualifier, label) — qualifier "a_partir_de" or "valor_base".
OFFERS = [
    ("product:chassis-wash", 450.0, "a_partir_de", "Lavagem de chassi"),
    ("product:engine-bay-wash", 190.0, "a_partir_de", "Lavagem de motor"),
    ("product:interior-cleaning", 650.0, "valor_base", "Higienização interna"),
    ("product:leather-conditioning", 490.0, "valor_base", "Hidratação dos couros"),
    ("product:glass-polish", 350.0, "a_partir_de", "Polimento de vidros"),
    ("product:commercial-polish", 650.0, "valor_base", "Polimento comercial"),
    ("product:headlight-restoration", 280.0, "valor_base", "Restauração de faróis"),
    ("product:technical-polish", 950.0, "a_partir_de", "Polimento técnico"),
    ("product:ppf", 650.0, "valor_base", "PPF — kit básico"),
    ("product:vitrification", 1550.0, "a_partir_de", "Vitrificação"),
    ("product:windshield-crystallization", 250.0, "a_partir_de", "Cristalização do para-brisa"),
    ("product:seat-vitrification", 350.0, "a_partir_de", "Vitrificação dos bancos"),
]
EXTRA_OFFERS = [
    # PPF multimídia is a separate starting price under the PPF service.
    ("offer:ppf:multimedia-starting-price", "product:ppf", 190.0, "a_partir_de", "PPF — multimídia"),
]

CONFIRM = "O valor o atendente confirma depois de avaliar o veículo."

# Existing FAQs whose answers carried prices or Aura-derived facts.
FAQ_REWRITES = {
    "faq:price-and-schedule": (
        "Os orçamentos são personalizados conforme o tamanho e as condições do veículo. "
        "Depois da avaliação presencial ou do envio de informações, a Utzig informa valor e "
        "prazo para reservar a agenda.",
        ["quanto custa", "qual o valor", "qual o preço", "tem tabela de preço",
         "como funciona o orçamento", "tem horário disponível", "como agendar"],
    ),
    "faq:site:service-duration": (
        "Em média: lavagem cerca de 3 horas, higienização interna cerca de 12 horas (secagem "
        "dos bancos), polimento cerca de 12 horas e vitrificação cerca de 3 dias.",
        ["quanto tempo demora", "quanto tempo leva", "fica pronto quando",
         "quantos dias fica o carro", "prazo do serviço"],
    ),
    "faq:site:ppf-benefit": (
        "O PPF é uma película transparente de proteção física contra riscos, arranhões e "
        "pequenos impactos. Pode ir em áreas críticas, em partes maiores ou no carro todo.",
        ["o que é ppf", "pra que serve o ppf", "ppf protege do que",
         "película de proteção da pintura", "vale a pena ppf"],
    ),
    "faq:site:budget": (
        "A avaliação e o orçamento são feitos pelo WhatsApp: mande fotos e informações do "
        "veículo, ou combine uma avaliação presencial.",
        ["como faço um orçamento", "quero um orçamento", "como pedir avaliação",
         "posso mandar foto", "como agendar avaliação"],
    ),
    "faq:service:detailed-wash:lavagem-detalhada-preco": (
        "A lavagem leva cerca de 3 horas. " + CONFIRM,
        None,
    ),
    "faq:service:interior-cleaning:higienizacao-preco-tempo": (
        "A higienização interna leva cerca de 12 horas, por causa da secagem dos bancos. " + CONFIRM,
        None,
    ),
    "faq:service:vitrification:vitrificacao-preco-tempo": (
        "A vitrificação leva cerca de 3 dias. " + CONFIRM,
        None,
    ),
    "faq:service:ppf:ppf-preco-tempo": (
        "O tempo do PPF depende das áreas escolhidas e é combinado na avaliação. " + CONFIRM,
        None,
    ),
}

# New FAQs: (id, parent, question, answer, aliases, claim_type, approved)
NEW_FAQS = [
    ("faq:utzig:services-overview", GLOBAL_PARENT,
     "Quais serviços a Utzig faz?",
     "A Utzig trabalha em três frentes: limpeza e higienização (lavagem detalhada, chassi, "
     "motor, higienização interna), brilho e correção (polimento comercial, técnico, de vidros "
     "e restauração de faróis) e proteção (vitrificação, vitrificação de plásticos e couros, "
     "cristalização do para-brisa e PPF).",
     ["o que vocês fazem", "quais serviços tem", "vocês fazem o quê", "lista de serviços",
      "serviços da utzig"], "public_information", True),
    ("faq:utzig:ppf-areas", "product:ppf",
     "Onde dá para aplicar PPF?",
     "Na pintura, em áreas críticas como conchas de maçaneta, quinas de portas e soleiras, e em "
     "partes maiores como para-choque, capô, teto e retrovisor — ou no carro todo.",
     ["onde aplica ppf", "ppf no capô", "ppf na maçaneta", "ppf no carro inteiro",
      "quais partes recebem ppf"], "service_detail", True),
    ("faq:utzig:ppf-interior", "product:ppf",
     "PPF serve para multimídia e painel?",
     "Sim. O PPF também pode ser aplicado em áreas sensíveis como multimídia, painéis e "
     "acabamentos em black piano.",
     ["ppf na multimídia", "ppf no painel", "proteger black piano", "película na central",
      "ppf interno"], "service_detail", True),
    ("faq:utzig:duration-wash", "product:detailed-wash",
     "Quanto tempo leva a lavagem?",
     "A lavagem leva cerca de 3 horas.",
     ["demora a lavagem", "lavagem fica pronta quando", "tempo da lavagem",
      "quantas horas a lavagem"], "service_detail", True),
    ("faq:utzig:duration-polish", "product:commercial-polish",
     "Quanto tempo leva o polimento?",
     "O polimento leva cerca de 12 horas.",
     ["demora o polimento", "tempo do polimento", "polimento fica pronto quando",
      "polimento é no mesmo dia"], "service_detail", True),
    ("faq:utzig:how-to-quote", GLOBAL_PARENT,
     "Como peço avaliação ou orçamento?",
     "Pelo WhatsApp: mande fotos e informações do veículo, ou combine uma avaliação presencial "
     "na Utzig.",
     ["quero orçamento", "como faço orçamento", "posso mandar fotos", "avaliação presencial",
      "como funciona a avaliação"], "public_information", True),
    # Inferred from "remover" in Luiza's notes: needs her confirmation before it
    # reaches the RAG (pending, no embedded edge).
    ("faq:utzig:services-not-offered", GLOBAL_PARENT,
     "Vocês fazem funilaria, pintura, envelopamento ou película?",
     "Não. A Utzig trabalha com limpeza, brilho e correção e proteção da pintura e do interior.",
     ["fazem funilaria", "fazem pintura", "fazem envelopamento", "colocam insulfilm",
      "película nos vidros"], "public_information", False),
]


def _faq_node(fid, question, answer, aliases, claim_type, approved, parent):
    status = "approved" if approved else "pending_validation"
    data = {
        "question": question,
        "answer": answer,
        "question_aliases": aliases,
        "aliases": aliases,
        "claims": [{
            "claim_type": claim_type,
            "evidence_node_ids": [fid],
            "policy": (
                {"mode": "informational"} if claim_type == "public_information"
                else "published_service_detail_with_source_provenance"
            ),
        }],
        "graph_json_node_id": fid,
        "source": SOURCE,
        "validation_status": status,
    }
    if parent == GLOBAL_PARENT:
        data["capabilities"] = {"global_context": True}
    return {
        "id": fid, "node_type": "faq", "slug": fid.replace(":", "-"),
        "status": status, "title": question, "summary": answer, "tags": [], "data": data,
    }


def _edge(eid, source, target, relation, primary=False):
    metadata = {"active": True, "graph_json_edge_id": eid}
    if primary:
        metadata["primary"] = True
    return {"id": eid, "source": source, "target": target, "relation_type": relation,
            "weight": 1.0, "metadata": metadata}


def build() -> tuple[dict, dict]:
    base = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in base["nodes"]}
    edges = base["edges"]

    # 1. Retirement set: roots plus their exclusive faq/copy/offer/asset children.
    retired = set(RETIRED_ROOTS) | set(RETIRED_EXTRA)
    changed = True
    while changed:
        changed = False
        for edge in edges:
            target = edge["target"]
            if (edge["source"] in retired and target not in retired
                    and edge["relation_type"] in {"contains", "answers_question"}
                    and target.split(":")[0] in {"faq", "copy", "offer", "asset"}):
                parents = {e["source"] for e in edges
                           if e["target"] == target and e["relation_type"] == "contains"}
                if parents <= retired:
                    retired.add(target)
                    changed = True
    retired_edges = [e for e in edges if e["source"] in retired or e["target"] in retired]

    patch_nodes = []
    for node_id, title in {**SECTOR_TITLES, **PRODUCT_TITLES}.items():
        patch_nodes.append({"id": node_id, "patch": {"title": title}})

    # 2. Vehicle and name belong to the lead (carry over between attendances).
    for node in base["nodes"]:
        qualification = (node.get("data") or {}).get("qualification")
        if node["id"] in retired or not isinstance(qualification, dict):
            continue
        fields = deepcopy(qualification.get("fields") or [])
        touched = False
        for field in fields:
            if isinstance(field, dict) and field.get("key") in {"modelo_veiculo", "nome_cliente"}:
                if field.get("key") == "modelo_veiculo":
                    field["depends_on"] = []
                if field.get("key") == "nome_cliente":
                    # The CRM/WhatsApp profile name is confirmed once ("Posso te
                    # chamar de Allan?") instead of asked again; one word is a name.
                    field["validation"] = {
                        **(field.get("validation") or {}),
                        "semantic_type": "human_full_name", "min_tokens": 1, "max_tokens": 6,
                    }
                    field["scope"] = "persona"
                field["carry_over"] = True
                touched = True
        if touched:
            patch_nodes.append({"id": node["id"], "patch": {"data": {"qualification": {"fields": fields}}}})

    # 3. Prices from Luiza: offers only (public site / closer), never SDR text.
    upsert_nodes, upsert_edges = [], []
    for product, amount, qualifier, label in OFFERS:
        slug = product.split(":", 1)[1]
        offer_id = f"offer:{slug}:starting-price"
        offer = {
            "id": offer_id, "node_type": "offer", "slug": f"{slug}-starting-price",
            "status": "approved",
            "title": f"Preço — {label}",
            "summary": f"{label} {'a partir de ' if qualifier == 'a_partir_de' else ''}R$ {amount:.2f}".replace(".", ","),
            "tags": [],
            "data": {
                "offer": {"amount": amount, "currency": "BRL"},
                "price_qualifier": qualifier,
                # A service has no fixed price: this is a reference the client
                # gave, registered so it can be switched back on later. It is
                # not shown on the site and the SDR never knows it.
                "price_kind": "service_reference",
                "visibility": "registered_only",
                "graph_json_node_id": offer_id,
                "source": SOURCE,
                "validation_status": "approved",
            },
        }
        if offer_id in nodes:
            patch_nodes.append({"id": offer_id, "patch": {k: offer[k] for k in ("title", "summary", "data")}})
        else:
            upsert_nodes.append(offer)
            upsert_edges.append(_edge(f"edge:{slug}:offer:contains", product, offer_id, "contains", True))
            upsert_edges.append(_edge(f"edge:{slug}:offer:about", offer_id, product, "about_product"))
    for offer_id, product, amount, qualifier, label in EXTRA_OFFERS:
        upsert_nodes.append({
            "id": offer_id, "node_type": "offer", "slug": offer_id.replace(":", "-"),
            "status": "approved", "title": f"Preço — {label}",
            "summary": f"{label} a partir de R$ {amount:.2f}".replace(".", ","), "tags": [],
            "data": {"offer": {"amount": amount, "currency": "BRL"}, "price_qualifier": qualifier,
                     "price_kind": "service_reference", "visibility": "registered_only",
                     "graph_json_node_id": offer_id, "source": SOURCE,
                     "validation_status": "approved"},
        })
        upsert_edges.append(_edge(f"edge:{offer_id}:contains", product, offer_id, "contains", True))
        upsert_edges.append(_edge(f"edge:{offer_id}:about", offer_id, product, "about_product"))

    # Lavagem detalhada has no client-confirmed price (R$ 259,90 came from the
    # Aura reference): keep the node, drop the value.
    patch_nodes.append({"id": "offer:detailed-wash:starting-price", "patch": {
        "title": "Preço — Lavagem detalhada",
        "summary": "Lavagem detalhada sem preço registrado pela Utzig",
        "data": {"offer": None, "price_kind": "service_reference",
                 "visibility": "registered_only", "source": SOURCE,
                 "price_status": "not_provided_by_client"},
    }})

    # 4. FAQ rewrites (no prices in SDR-retrievable text).
    for faq_id, (answer, aliases) in FAQ_REWRITES.items():
        data_patch = {"answer": answer, "source": SOURCE, "validation_status": "approved"}
        if aliases:
            data_patch["question_aliases"] = aliases
            data_patch["aliases"] = aliases
        patch_nodes.append({"id": faq_id, "patch": {"summary": answer, "data": data_patch}})

    # 4b. No FAQ answer anywhere keeps a money value (the SDR never knows prices).
    rewritten = set(FAQ_REWRITES)
    for node in base["nodes"]:
        answer = str((node.get("data") or {}).get("answer") or "")
        if (node.get("node_type") != "faq" or node["id"] in rewritten
                or (RETIRE_NODES and node["id"] in retired) or not MONEY.search(answer)):
            continue
        kept = [part for part in SENTENCE.split(answer) if not MONEY.search(part)]
        clean = (" ".join(kept).strip() + " " + CONFIRM).strip()
        patch_nodes.append({"id": node["id"], "patch": {"summary": clean, "data": {"answer": clean}}})

    # 4c. Production has a second, empty gallery (gallery:gallery-default, no
    # edges) created by asset uploads outside the bundle. The public site needs
    # exactly one gallery (gallery:utzig), so the empty one is archived at
    # publication (read 2026-10-02, projection c5220eae-994b-45ec-8ea9-34fea41a2885).
    production_only_retired = [{
        "id": "gallery:gallery-default", "node_type": "gallery", "slug": "gallery-default",
        "removal_reason": "galeria_vazia_duplicada_criada_por_upload",
    }]

    # 5. New FAQs. A bundle only carries publishable nodes: FAQs awaiting the
    # client's confirmation are written to PENDING_FILE instead.
    pending = []
    for fid, parent, question, answer, aliases, claim_type, approved in NEW_FAQS:
        if not approved:
            pending.append(_faq_node(fid, question, answer, aliases, claim_type, False, parent)
                           | {"parent": parent})
            continue
        upsert_nodes.append(_faq_node(fid, question, answer, aliases, claim_type, approved, parent))
        upsert_edges.append(_edge(f"edge:{fid}:contains", parent, fid, "contains", True))
        upsert_edges.append(_edge(f"edge:{fid}:answers", parent, fid, "answers_question"))
        if approved:
            upsert_edges.append(_edge(f"edge:{fid}:embedded", fid, EMBEDDED, "publishes_to"))

    # 6. Landing page blocks (Luiza's order; showcase removed; three sectors).
    campaign = nodes["campaign:automotive-detailing"]
    blocks = {block["id"]: deepcopy(block) for block in campaign["data"]["page"]["blocks"]}
    blocks["lp-hero"]["title"] = "Utzig Estética automotiva Santa Maria do Herval"
    blocks["lp-hero"]["description"] = (
        "Limpeza e higienização, brilho e correção e proteção para o seu carro."
    )
    blocks["lp-services"]["node_ids"] = [
        "group:cleaning", "product:detailed-wash", "product:chassis-wash",
        "product:engine-bay-wash", "product:interior-cleaning", "product:leather-conditioning",
        "group:revitalization", "product:commercial-polish", "product:technical-polish",
        "product:glass-polish", "product:headlight-restoration",
        "group:enhancement", "product:vitrification", "product:seat-vitrification",
        "product:windshield-crystallization", "product:ppf",
    ]
    blocks["lp-process"]["eyebrow"] = "Avaliação e orientação"
    blocks["lp-gallery"]["eyebrow"] = "Resultados"
    blocks["lp-location"]["eyebrow"] = "Venha conhecer nosso espaço"
    blocks["lp-faq"]["node_ids"] = [
        node_id for node_id in blocks["lp-faq"]["node_ids"] if node_id not in retired
    ]
    order = ["lp-hero", "lp-audiences", "lp-services", "lp-process", "lp-gallery",
             "lp-location", "lp-faq", "lp-specialist", "lp-final"]
    page = deepcopy(campaign["data"]["page"])
    page["blocks"] = [blocks[block_id] for block_id in order]
    patch_nodes.append({"id": campaign["id"], "patch": {"data": {"page": page}}})

    # Campaign blocks and edges pointing at retired nodes must not dangle.
    if not RETIRE_NODES:
        # v15a: the services stay in the graph (and in the SDR) until v15b; the
        # site no longer lists them and their offers are registered only.
        for node_id in sorted(retired):
            node = nodes[node_id]
            if node["node_type"] == "offer":
                patch_nodes.append({"id": node_id, "patch": {"data": {
                    "price_kind": "service_reference", "visibility": "registered_only"}}})
        retired, retired_edges = set(), []

    overlay = {
        "overlay_version": "1.0",
        "base_publication": ACTIVE,
        "metadata": {
            "purpose": "Utzig commercial alignment: three sectors, Luiza prices on offers only, "
                       "services discontinued, retrievable FAQs, lead-scoped vehicle and name",
            "source": SOURCE,
            "retired_nodes": [
                {"id": node_id, "node_type": nodes[node_id]["node_type"],
                 "slug": nodes[node_id]["slug"], "removal_reason": REMOVAL_REASON}
                for node_id in sorted(retired)
            ] + production_only_retired,
            "visual_media_reconciliation": {
                "soft_disabled_edges": [
                    {"id": e["id"], "source": e["source"], "target": e["target"],
                     "relation_type": e["relation_type"], "removal_reason": REMOVAL_REASON}
                    for e in sorted(retired_edges, key=lambda e: e["id"])
                ],
                "soft_disabled_edge_count": len(retired_edges),
            },
        },
        "remove_edge_ids": sorted(e["id"] for e in retired_edges),
        "remove_node_ids": sorted(retired),
        "upsert_nodes": upsert_nodes,
        "patch_nodes": patch_nodes,
        "upsert_edges": upsert_edges,
    }
    publication = {"id": ACTIVE["publication_id"], "version": ACTIVE["version"],
                   "checksum": ACTIVE["checksum"]}
    bundle = apply_overlay(base, overlay, publication)
    bundle["metadata"]["publication_allowed"] = True
    # The real baseline is the active v13 publication, not the v12 pointer the
    # v13 source file still carries.
    bundle["metadata"]["baseline_publication"] = dict(ACTIVE)
    return overlay, bundle, pending


def main() -> int:
    overlay, bundle, pending = build()
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OVERLAY_FILE.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BUNDLE_FILE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "retired_nodes": len(overlay["metadata"]["retired_nodes"]),
        "soft_disabled_edges": overlay["metadata"]["visual_media_reconciliation"]["soft_disabled_edge_count"],
        "new_nodes": len(overlay["upsert_nodes"]),
        "patched_nodes": len(overlay["patch_nodes"]),
        "new_edges": len(overlay["upsert_edges"]),
        "bundle_nodes": len(bundle["nodes"]),
        "bundle_edges": len(bundle["edges"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
