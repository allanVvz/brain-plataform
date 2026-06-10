from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc  # noqa: E402


def _entry(content_type: str, slug: str, parent_slug: str | None, title: str | None = None) -> dict:
    metadata = {"parent_slug": parent_slug} if parent_slug else {}
    return {
        "content_type": content_type,
        "slug": slug,
        "title": title or slug.replace("-", " ").title(),
        "content": title or slug.replace("-", " "),
        "metadata": metadata,
    }


def _vz_session() -> dict:
    return {
        "context": "Missao: vz-lupas | Fonte: https://vzlupas.com | Blocos: briefing, audience, product, copy, faq",
        "persona_slug": "vz-lupas",
        "classification": {"persona_slug": "vz-lupas"},
        "initial_block_counts": {
            "brand": 1,
            "briefing": 1,
            "campaign": 1,
            "audience": 1,
            "product_group": 3,
            "product": 9,
            "copy": 9,
            "faq": 9,
        },
        "messages": [
            {
                "role": "user",
                "content": (
                    "estraia do site 9 produtos juliet plantaris e radar 3 grupos "
                    "3 produtos em cada. comunicacao comercial jovem. audiencia "
                    "padrao. campanha de retorno da vz inverno"
                ),
            },
            {"role": "user", "content": "gere prossiga"},
        ],
    }


def test_preview_accepts_main_tree_when_complementary_nodes_are_pending() -> None:
    previous = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        entries = [
            _entry("brand", "vz-lupas", "self", "Vz Lupas"),
            _entry("briefing", "briefing-captura-vz", "vz-lupas", "Briefing Captura VZ"),
            _entry("campaign", "campanha-retorno-vz-inverno", "briefing-captura-vz", "Campanha de Retorno VZ Inverno"),
            _entry("audience", "publico-padrao-jovem", "campanha-retorno-vz-inverno", "Publico padrao jovem"),
        ]
        for group in ("juliet", "plantaris", "radar"):
            entries.append(_entry("product_group", group, "publico-padrao-jovem", group.title()))
            for idx in range(1, 4):
                entries.append(_entry("product", f"{group}-produto-{idx}", group, f"{group.title()} Produto {idx}"))

        state = svc.normalize_validate_summarize_plan(
            {"persona_slug": "vz-lupas", "entries": entries},
            _vz_session(),
        )
    finally:
        if previous is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = previous

    validation = state["validation"]
    assert validation["blocking_violations"] == []
    warnings = "\n".join(validation["warnings"])
    assert "pending_copy" in warnings
    assert "pending_faq" in warnings
    assert "pending_embedded" in warnings
    assert "pending_terminal_connection" in warnings
