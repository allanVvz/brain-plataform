#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def parent_slug(entry: dict) -> str:
    return str((entry.get("metadata") or {}).get("parent_slug") or "")


def main() -> int:
    session = {
        "id": "e2e-tockfatal-plan-contract",
        "context": """
# Plano confirmado pelo operador
persona_slug: tock-fatal
fonte principal: https://tockfatal.com

## Variacoes por atributo
- briefing: 1 variacao(oes) por ramo
- campaign: 1 variacao(oes) por ramo
- audience: 2 variacao(oes) por ramo
- product: 6 variacao(oes) por ramo
- entity: 1 variacao(oes) por ramo
- copy: 1 variacao(oes) por ramo
- faq: 8 variacao(oes) por ramo
- rule: 1 variacao(oes) por ramo

Kit Modal 1 e Kit Modal 2.
Ambos tem os mesmos valores:
1 peca R$ 59,90
5 pecas R$ 249,00
10 pecas R$ 459,00.
1 peca e para cliente final.
5 e 10 pecas sao para empreendedoras.
""",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Kit Modal 1 e Kit Modal 2. Ambos tem os mesmos valores: "
                    "1 peca R$ 59,90; 5 pecas R$ 249,00; 10 pecas R$ 459,00. "
                    "1 peca e para cliente final. 5 e 10 pecas sao para empreendedoras."
                ),
            }
        ],
        "classification": {"persona_slug": "tock-fatal"},
    }
    raw_plan = {
        "source": "https://tockfatal.com",
        "persona_slug": "tock-fatal",
        "tree_mode": "pyramidal",
        "entries": [
            {"content_type": "briefing", "title": "Briefing Tock Fatal", "slug": "briefing-tock-fatal", "content": "Briefing", "metadata": {}},
            {"content_type": "campaign", "title": "Campanha Kits Modal", "slug": "campaign-tockfatal-kits-modal", "content": "Campanha", "metadata": {"parent_slug": "briefing-tock-fatal"}},
            {"content_type": "audience", "title": "Clientes finais", "slug": "audience-clientes-finais", "content": "Clientes finais", "metadata": {"parent_slug": "campaign-tockfatal-kits-modal"}},
            {"content_type": "audience", "title": "Mulheres empreendedoras", "slug": "audience-mulheres-empreendedoras", "content": "Empreendedoras revendedoras", "metadata": {"parent_slug": "campaign-tockfatal-kits-modal"}},
            {"content_type": "product", "title": "Kit Modal 1", "slug": "produto-kit-modal-1-audience-mulheres-empreendedoras", "content": "Kit Modal 1", "metadata": {}},
            {"content_type": "product", "title": "Kit Modal 2", "slug": "produto-kit-modal-2-audience-mulheres-empreendedoras", "content": "Kit Modal 2", "metadata": {}},
            {"content_type": "copy", "title": "Copy comercial", "slug": "copy-comercial", "content": "Copy", "metadata": {}},
            {"content_type": "rules", "title": "Regra publico quantidade", "slug": "rule-regra-publico-quantidade", "content": "1 peca cliente final; 5 e 10 empreendedoras", "metadata": {}},
            *[
                {"content_type": "faq", "title": f"FAQ {idx}", "slug": f"faq-{idx}", "content": f"Pergunta {idx}? Resposta {idx}.", "metadata": {}}
                for idx in range(1, 33)
            ],
        ],
        "links": [],
    }

    normalized = svc._normalize_sofia_knowledge_plan(raw_plan, session)  # type: ignore[attr-defined]
    violations = svc.validate_sofia_knowledge_plan(normalized, session=session)
    summary = svc.summarize_normalized_plan(normalized)  # type: ignore[attr-defined]
    counts = summary["current_block_counts"]
    entries = normalized["entries"]
    by_slug = {entry["slug"]: entry for entry in entries}

    expect(violations == [], f"normalized plan has no violations: {violations}")
    expect(normalized["tree_mode"] == "pyramidal", "tree_mode remains pyramidal")
    expect(normalized["branch_policy"] == "top_down_pyramidal", "branch_policy remains top_down_pyramidal")
    expect(normalized["faq_count_policy"] == "per_branch", "faq_count_policy defaults to Golden Dataset per branch")
    expect(counts["briefing"] == 1, "one briefing")
    expect(counts["campaign"] == 1, "one campaign")
    expect(counts["audience"] == 2, "two audiences")
    expect(counts["product"] == 4, "two base products distributed across two audiences")
    expect(counts["offer"] == 12, "offers are created for each product/audience quantity branch")
    expect(counts["copy"] >= 12, "copy exists for every offer")
    expect(counts["faq"] == counts["copy"], "one FAQ Golden Dataset is created per terminal copy")
    expect(counts["rule"] >= 1, "commercial rule exists")
    expect(all(entry["content_type"] != "rules" for entry in entries), "rules alias normalized to rule")
    expect(all("audience" not in entry["slug"] for entry in entries if entry["content_type"] == "product"), "product slug does not embed audience")

    offers = [entry for entry in entries if entry["content_type"] == "offer"]
    offer_qtys = sorted({int((entry.get("metadata") or {}).get("quantity") or 0) for entry in offers})
    expect(offer_qtys == [1, 5, 10], "offer quantities include 1, 5 and 10")

    for rule in [entry for entry in entries if entry["content_type"] == "rule"]:
        parent = by_slug.get(parent_slug(rule))
        expect(parent and parent["content_type"] in {"campaign", "briefing", "brand"}, "rule is attached to governing scope")

    for copy in [entry for entry in entries if entry["content_type"] == "copy"]:
        parent = by_slug.get(parent_slug(copy))
        expect(parent and parent["content_type"] == "offer", f"copy {copy['slug']} is below offer")

    for faq in [entry for entry in entries if entry["content_type"] == "faq"]:
        parent = by_slug.get(parent_slug(faq))
        expect(parent and parent["content_type"] == "copy", f"faq {faq['slug']} is below copy")

    expect(summary["current_block_counts"] == svc.count_blocks_by_type(entries), "summary matches normalized plan counts")
    expect(len(normalized.get("links") or []) > 0, "links are built only after valid normalization")
    print("summary", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
