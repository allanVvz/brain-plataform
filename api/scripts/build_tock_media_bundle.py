"""Build the deterministic Tock Fatal v11 media GraphBundle from v10."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v10-full-catalog.json"
TARGET = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v11-product-media.json"
MEDIA_DIR = ROOT / "docs/sdr/tock-fatal/product-media"
MANIFEST = MEDIA_DIR / "manifest.json"
SOURCE_KEY = "operator_approved_tock_product_media_2026-08-26"
GALLERY_ID = "gallery:tock-default"
EMBED_ID = "embed:tock-default"
CAMPAIGN_ID = "campaign:tock-whatsapp-qualification"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_id(product_id: str) -> str:
    return "asset:" + product_id.removeprefix("product:") + "-primary-image"


def build() -> dict:
    bundle = deepcopy(_load(SOURCE))
    manifest = _load(MANIFEST)
    node_by_id = {str(node["id"]): node for node in bundle["nodes"]}

    if manifest.get("source") != SOURCE_KEY:
        raise ValueError("unexpected media manifest source")
    for item in manifest.get("items") or []:
        path = MEDIA_DIR / str(item["file"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != str(item["sha256"]).lower():
            raise ValueError(f"media checksum mismatch: {path.name}")
        if item["product_node_id"] not in node_by_id:
            raise ValueError(f"published product missing: {item['product_node_id']}")

    bundle["metadata"].update({
        "purpose": "tock_fatal_v11_full_catalog_product_media",
        "media_source": SOURCE_KEY,
        "media_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "media_asset_count": len(manifest["items"]),
        "media_batch_max_items": 20,
    })
    persona = node_by_id["persona:tock-fatal"]
    conversation_policy = persona["data"].setdefault("conversation_policy", {})
    conversation_policy["content_delivery"] = {
        "enabled": True,
        "request_kind": "media",
        "allowed_media_types": ["image"],
        "asset_role": "primary_product_media",
        "max_items": 20,
        "selection_mode": "request_only",
        "batch_policy": "all_or_nothing",
        "delivery_order": "requested_product_order",
        "responses": {
            "clarify": "Quais pecas voce quer ver? Pode enviar os nomes na mesma mensagem.",
            "limit": "Consigo enviar ate 20 fotos por pedido. Quais 20 pecas voce quer priorizar?",
            "unavailable": "Ainda nao tenho foto aprovada para todas essas pecas. Quais delas voce quer priorizar para eu conferir?"
        }
    }

    rule_id = "rule:tock-product-media-delivery"
    copy_id = "copy:tock-product-media-delivery"
    faq_id = "faq:tock-product-media-delivery"
    bundle["nodes"].extend([
        {
            "id": rule_id,
            "node_type": "rule",
            "slug": "product-media-delivery",
            "title": "Regra de envio de imagens do catalogo",
            "summary": "Envia apenas imagens aprovadas e ligadas ao produto solicitado, em lote sequencial de ate 20 itens.",
            "status": "validated",
            "data": {
                "source": SOURCE_KEY,
                "status": "validated",
                "instruction": "Quando o cliente pedir fotos, identifique todos os produtos pelo grafo e marque a duvida como kind=media. Nao invente produto, URL, preco, estoque, cor, tamanho ou disponibilidade. O backend resolve o lote; se houver duvida, peca os nomes das pecas.",
                "max_items": 20,
                "all_or_nothing": True
            }
        },
        {
            "id": copy_id,
            "node_type": "copy",
            "slug": "product-media-delivery",
            "title": "Copy - envio de imagens do catalogo",
            "summary": "Posso enviar as fotos aprovadas das pecas que voce escolher. Pode mandar todos os nomes na mesma mensagem.",
            "status": "validated",
            "data": {
                "source": SOURCE_KEY,
                "status": "validated",
                "channel": "whatsapp",
                "content": "Posso enviar as fotos aprovadas das pecas que voce escolher. Pode mandar todos os nomes na mesma mensagem."
            }
        },
        {
            "id": faq_id,
            "node_type": "faq",
            "slug": "product-media-delivery",
            "title": "Posso pedir fotos de varias roupas de uma vez?",
            "summary": "Sim. Podem ser solicitadas em uma mensagem as fotos aprovadas de ate 20 pecas publicadas.",
            "status": "validated",
            "data": {
                "source": SOURCE_KEY,
                "status": "validated",
                "question": "Posso pedir fotos de varias roupas de uma vez?",
                "aliases": [
                    "me manda as fotos dessas pecas",
                    "quero ver varias roupas",
                    "manda todas as fotos de uma vez"
                ],
                "answer": "Sim. Voce pode pedir, na mesma mensagem, as fotos aprovadas de ate 20 pecas publicadas. Se algum nome estiver ambiguo ou alguma foto nao estiver aprovada, vou pedir que voce esclareca antes do envio. A foto nao confirma preco, estoque, cor, tamanho ou disponibilidade."
            }
        }
    ])
    bundle["edges"].extend([
        {"id": "edge:tock-campaign-product-media-rule", "source": CAMPAIGN_ID, "target": rule_id, "relation_type": "contains"},
        {"id": "edge:tock-campaign-product-media-copy", "source": CAMPAIGN_ID, "target": copy_id, "relation_type": "contains"},
        {"id": "edge:tock-copy-product-media-faq", "source": copy_id, "target": faq_id, "relation_type": "contains"},
        {"id": "edge:tock-faq-product-media-embed", "source": faq_id, "target": EMBED_ID, "relation_type": "publishes_to"}
    ])

    for item in manifest["items"]:
        product_id = str(item["product_node_id"])
        product = node_by_id[product_id]
        asset_id = _asset_id(product_id)
        bundle["nodes"].append({
            "id": asset_id,
            "node_type": "asset",
            "slug": product["slug"] + "-primary-image",
            "title": "Imagem principal - " + str(product["title"]),
            "summary": "Imagem aprovada do produto " + str(product["title"]) + ".",
            "tags": ["catalogo", "produto", "imagem-aprovada"],
            "status": "validated",
            "data": {
                "source": SOURCE_KEY,
                "status": "validated",
                "asset_role": "primary_product_media",
                "product_node_id": product_id,
                "media": {
                    "kind": "image",
                    "mime": item["mime"],
                    "bucket": "assets-raw",
                    "path": "tock-fatal/product-media/" + item["file"],
                    "filename": item["file"],
                    "sha256": item["sha256"]
                },
                "local_evidence_path": "docs/sdr/tock-fatal/product-media/" + item["file"]
            }
        })
        suffix = product["slug"]
        bundle["edges"].extend([
            {"id": "edge:tock-product-asset-" + suffix, "source": product_id, "target": asset_id, "relation_type": "contains"},
            {"id": "edge:tock-asset-gallery-" + suffix, "source": asset_id, "target": GALLERY_ID, "relation_type": "gallery_asset"}
        ])

    return bundle


def main() -> int:
    payload = build()
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(TARGET), "nodes": len(payload["nodes"]), "edges": len(payload["edges"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
