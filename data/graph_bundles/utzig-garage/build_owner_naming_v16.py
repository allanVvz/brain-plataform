"""Build Utzig v16: refer to the owner as Wilian, never by a nickname.

Base: the active v15 publication (bundle utzig-commercial-alignment-v15.json,
publication version 14). The business is "Utzig Garage do Wilian", alternating
with "Utzig" and "Wilian". Internal ids and asset file names are unchanged.

Run from the repository root:
    python data/graph_bundles/utzig-garage/build_owner_naming_v16.py
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_FILE = HERE / "utzig-commercial-alignment-v15.json"
BUNDLE_FILE = HERE / "utzig-owner-naming-v16.json"
ACTIVE = {
    "publication_id": "e10f7558-2232-47f2-9a0b-efdcae7c1c3e",
    "version": 14,
    "checksum": "sha256:217d45637011f85e8a6be888e033d37430acfe815c8f4085336251f21f019ddf",
}
SOURCE = "user_request_2026_10_02_owner_naming"
NAMING_RULE = (
    "Refira-se ao negócio como Utzig Garage do Wilian, alternando com Utzig e "
    "Wilian. Nunca use apelido para o dono."
)
# Keys that are identifiers, never customer-facing text.
SKIP_KEYS = {"id", "slug", "graph_json_node_id", "url", "storage_url", "public_url",
             "source", "source_node_id", "projection_node_id", "asset_id", "filename"}
EXACT = [
    ("Wilian, o Alemão da Utzig", "Wilian, da Utzig Garage"),
    ("Wilian — O Alemão da Utzig", "Wilian — Utzig Garage"),
    ("O Alemão da Utzig", "Utzig Garage do Wilian"),
    ("Olá, gostaria de falar com o Alemão.", "Olá, Wilian! Gostaria de conversar."),
    ("Falar com o Alemão", "Falar com o Wilian"),
]
GENERIC = [
    (re.compile(r"\bfingir ser o Alem[aã]o\b"), "fingir ser o Wilian"),
    (re.compile(r"\b(ao|pelo|do|para o|com o) Alem[aã]o\b"), r"\1 Wilian"),
    (re.compile(r"\b[Oo] Alem[aã]o\b"), "o Wilian"),
    (re.compile(r"\bAlem[aã]o\b"), "Wilian"),
]
CONFIRM_FAQ = re.compile(r"O Alem[aã]o confirma avalia[cç][aã]o, valor e pr[oó]ximos passos\.")
NICKNAME = re.compile(r"alem[aã]o", re.IGNORECASE)


def _fix_text(value: str) -> str:
    for old, new in EXACT:
        value = value.replace(old, new)
    for pattern, new in GENERIC:
        value = pattern.sub(new, value)
    # Sentence starts stay capitalised after the generic replacement.
    return re.sub(r"(^|[.!?]\s+)o Wilian", lambda m: m.group(1) + "O Wilian", value)


def _walk(value, key=""):
    if isinstance(value, dict):
        return {k: (v if k in SKIP_KEYS else _walk(v, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(item, key) for item in value]
    if isinstance(value, str) and NICKNAME.search(value):
        return _fix_text(value)
    return value


def build() -> dict:
    bundle = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    faq_index = 0
    for node in bundle["nodes"]:
        # Alternate the service FAQ closing between Utzig and Wilian.
        answer = str((node.get("data") or {}).get("answer") or "")
        if node.get("node_type") == "faq" and CONFIRM_FAQ.search(answer):
            closing = ("A Utzig confirma avaliação, valor e próximos passos." if faq_index % 2 == 0
                       else "O Wilian confirma avaliação, valor e próximos passos.")
            faq_index += 1
            node["data"]["answer"] = CONFIRM_FAQ.sub(closing, answer)
            if CONFIRM_FAQ.search(str(node.get("summary") or "")):
                node["summary"] = CONFIRM_FAQ.sub(closing, str(node["summary"]))
        for key in ("title", "summary", "data"):
            if key in node:
                node[key] = _walk(node[key], key)

    nodes = {node["id"]: node for node in bundle["nodes"]}
    persona = nodes["persona:utzig-garage"]
    persona["summary"] = (
        "Assistente virtual sem nome da Utzig Garage do Wilian: entende a necessidade "
        "e encaminha o atendimento ao Wilian. " + NAMING_RULE
    )
    persona["data"]["conversation_policy"]["opening"]["first_turn"] = (
        "Apresente-se uma vez como assistente virtual da Utzig Garage do Wilian, "
        "sem usar nome próprio e sem fingir ser o Wilian."
    )
    persona["data"]["agent_identity"]["company"] = "Utzig Garage do Wilian"
    persona["data"]["agent_identity"]["owner_reference"] = NAMING_RULE
    tone = nodes["tone:consultative"]
    tone["summary"] = (str(tone.get("summary") or "").rstrip(". ") + ". " + NAMING_RULE).lstrip(". ")
    brand = nodes["brand:utzig-garage"]
    brand["summary"] = "Utzig Garage do Wilian: estética automotiva em Santa Maria do Herval."

    metadata = bundle["metadata"]
    metadata["purpose"] = "Utzig v16: owner referred to as Wilian; no nickname in any text"
    metadata["source"] = SOURCE
    metadata["baseline_publication"] = dict(ACTIVE)
    metadata["publication_allowed"] = True
    # v15 already archived its retired nodes and edges; nothing to retire now.
    metadata.pop("retired_nodes", None)
    metadata.pop("visual_media_reconciliation", None)

    leftovers = []
    def scan(value, path):
        if isinstance(value, dict):
            for k, v in value.items():
                if k not in SKIP_KEYS:
                    scan(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                scan(v, f"{path}[{i}]")
        elif isinstance(value, str) and NICKNAME.search(value) and " " in value:
            # Human-readable text has spaces; ids, slugs and file paths do not.
            leftovers.append((path, value))
    for node in bundle["nodes"]:
        for key in ("title", "summary", "data"):
            scan(node.get(key), f"{node['id']}.{key}")
    if leftovers:
        raise SystemExit("nickname left in customer-facing text: " + json.dumps(leftovers[:5], ensure_ascii=False))
    return bundle


def main() -> int:
    bundle = build()
    BUNDLE_FILE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle_nodes": len(bundle["nodes"]), "bundle_edges": len(bundle["edges"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
