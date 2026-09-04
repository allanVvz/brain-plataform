"""Build the Tock Fatal v16 GraphBundle: make the persona's voice reachable.

## The defect this fixes

`conversation_runtime.build_system_prompt` composes the agentic system prompt
from the persona's own graph, reading each tone and rule node as
`data.markdown or data.summary`. Tock Fatal's tone nodes carry only a one-line
`summary`; the concrete instructions live in structures the builder never
reads:

    tone:tock-vitoria-voice          data.voice.style[]      data.voice.guidelines[]
    tone:tock-vitoria-clear-language data.guidelines[]
    rule:tock-desconto-atacado-30    data.facts[]
    rule:tock-safe-handoff           data.handoff_rule{}

So the model was told *"Vitória conversa de forma acolhedora, simples e
direta"* and never told the seven guidelines that say what that means --
"responda primeiro ao conteúdo que a pessoa trouxe", "use frases curtas e
palavras comuns", "não force pergunta em saudação", "peça o nome naturalmente;
o nome não bloqueia ajuda inicial". The most specific description of how this
persona speaks was dead data.

## The fix

Render those structures into `data.markdown` on each tone and rule node, which
`build_system_prompt` already prefers over `summary`. No runtime change: the
content simply becomes reachable through the path that already exists.

The rendering is generic -- any node carrying `voice.guidelines`, `guidelines`,
`facts` or `handoff_rule` is rendered the same way -- so this is not a Tock
special case even though the script is per-persona, matching v12/v14/v15.

Nothing else moves. Offers, prices, products, FAQs and every commercial claim
stay byte-stable.

    python api/scripts/build_tock_fatal_v16.py <source> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

BASELINE_PURPOSE = "tock_fatal_v15_flow_faqs"

# build_system_prompt caps tone and rule blocks at 1500 tokens each (~6000
# chars). Rendering stays well inside that so nothing gets silently dropped.
RENDERED_NODE_TYPES = ("tone", "rule")


def _bullets(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [f"- {str(item).strip()}" for item in values if str(item or "").strip()]


def _render(node: dict[str, Any]) -> str | None:
    """Compose a markdown block from whatever structured guidance a node holds.

    Returns None when the node carries nothing beyond its summary, so an
    already-adequate node is left untouched.
    """
    data = node.get("data") or {}
    lines: list[str] = []

    title = str(node.get("title") or "").strip()
    summary = str(node.get("summary") or "").strip()
    if title:
        lines.append(f"## {title}")
    if summary:
        lines.append(summary)

    voice = data.get("voice") if isinstance(data.get("voice"), dict) else {}
    style = voice.get("style")
    if isinstance(style, list) and style:
        lines.append("Tom: " + ", ".join(str(item) for item in style if item) + ".")

    guidelines = _bullets(voice.get("guidelines")) or _bullets(data.get("guidelines"))
    if guidelines:
        lines.append("Como falar:")
        lines.extend(guidelines)

    facts = _bullets(data.get("facts"))
    if facts:
        lines.append("Fatos publicados:")
        lines.extend(facts)

    instruction = str(data.get("instruction") or "").strip()
    if instruction:
        lines.append(instruction)

    handoff = data.get("handoff_rule") if isinstance(data.get("handoff_rule"), dict) else {}
    handoff_text = str(handoff.get("text") or data.get("handoff_message") or "").strip()
    if handoff_text:
        condition = str(handoff.get("condition") or "").strip()
        prefix = f"Quando {condition}: " if condition else ""
        lines.append(f"{prefix}\"{handoff_text}\"")

    # Only worth rendering when there is something the summary did not already
    # say; a title plus the summary alone is not an improvement.
    body = [line for line in lines if line and not line.startswith("## ")]
    if len(body) <= 1:
        return None
    return "\n".join(lines).strip()


def _assert_baseline(bundle: dict[str, Any]) -> None:
    metadata = bundle.get("metadata") or {}
    if (bundle.get("persona") or {}).get("slug") != "tock-fatal":
        raise ValueError("the baseline is not the Tock Fatal bundle")
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(
            f"expected the {BASELINE_PURPOSE} baseline, got {metadata.get('purpose')!r}"
        )
    kinds = {node.get("node_type") for node in bundle["nodes"]}
    for node_type in RENDERED_NODE_TYPES:
        if node_type not in kinds:
            raise ValueError(f"baseline has no {node_type} node to render")


def build(source: dict[str, Any]) -> dict[str, Any]:
    _assert_baseline(source)
    candidate = copy.deepcopy(source)

    rendered: list[str] = []
    for node in candidate["nodes"]:
        if node.get("node_type") not in RENDERED_NODE_TYPES:
            continue
        data = node.setdefault("data", {})
        if str(data.get("markdown") or "").strip():
            continue
        markdown = _render(node)
        if not markdown:
            continue
        data["markdown"] = markdown
        rendered.append(node["id"])

    candidate["metadata"] = {
        **(candidate.get("metadata") or {}),
        "purpose": "tock_fatal_v16_voice_reachable",
        "content_revision": "3.5-voice-reachable",
        "voice_rendered_node_ids": sorted(rendered),
        "change_summary": (
            "Diretrizes de voz e fatos de regra renderizados em data.markdown, "
            "que build_system_prompt já prefere. Antes disso o modelo recebia "
            "só o resumo de uma linha de cada nó de tom, e as sete diretrizes "
            "concretas da Vitória nunca chegavam ao prompt."
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
    rendered = candidate["metadata"]["voice_rendered_node_ids"]
    print(f"wrote {args.output}")
    print(f"  nós renderizados: {len(rendered)}")
    for node_id in rendered:
        print(f"    - {node_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
