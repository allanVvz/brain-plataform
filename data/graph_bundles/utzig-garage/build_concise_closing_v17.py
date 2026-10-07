"""Build Utzig v17: shorter, more human messages and a light closing.

Base: active v16 (publication version 15). Changes, graph only:
- tone: short messages (up to two short sentences), no repeated explanations,
  at most one emoji and only in the opening and closing messages;
- closing: after the customer confirms, one short message says Wilian continues
  and suggests (once, as a tip, not a question) sending a few photos of the
  vehicle, or bringing the car in person;
- script: `objective` leaves the service questions (it repeated the focus the
  customer had already given) and `procedimento_anterior` becomes optional;
- FAQs about photos, quotes by photo and in-person evaluation.

Run from the repository root:
    python data/graph_bundles/utzig-garage/build_concise_closing_v17.py
"""
from __future__ import annotations

import json
from pathlib import Path

from active_graph_bundle import load_active_bundle

HERE = Path(__file__).resolve().parent
BUNDLE_FILE = HERE / "utzig-concise-closing-v17.json"
SOURCE = "user_request_2026_10_02_concise_closing"
EMBEDDED = "embedded:utzig"
GLOBAL_PARENT = "rule:human-handoff"

STYLE = (
    "Mensagens curtas e objetivas: no máximo duas frases curtas por mensagem. "
    "Não repita explicações nem resumos já enviados. Emoji só na primeira mensagem "
    "e na mensagem de encerramento, no máximo um."
)
NAMING = (
    "Refira-se ao negócio como Utzig Garage do Wilian, alternando com Utzig e "
    "Wilian. Nunca use apelido para o dono."
)
CLOSING = (
    "Quando o cliente confirmar o resumo, encerre em uma mensagem curta: diga que o "
    "Wilian vai continuar o atendimento e, uma única vez, dê a dica de que fotos do "
    "veículo (da área do serviço, com boa luz) ajudam a adiantar a avaliação, e que "
    "também dá para levar o carro pessoalmente. É uma sugestão, não uma pergunta: "
    "não insista nem volte ao assunto se a pessoa não mandar."
)
COMPLETION = (
    "Perfeito! Vou passar seu pedido pro Wilian, que continua o atendimento por aqui. "
    "Se puder, mande umas fotos da área do carro: ajuda a adiantar a avaliação. "
    "Se preferir, também dá pra levar o carro pessoalmente."
)

# (id, question, answer, aliases)
NEW_FAQS = [
    ("faq:utzig:photos-what", "Que fotos devo mandar?",
     "Fotos da área do serviço, de perto e de um pouco mais longe, com boa luz.",
     ["quais fotos mando", "como tirar a foto", "foto de qual parte", "que foto precisa",
      "mando foto de onde"]),
    ("faq:utzig:photos-optional", "Preciso mandar foto?",
     "Não é obrigatório. As fotos só ajudam a adiantar; o Wilian também avalia com o carro "
     "na Utzig.",
     ["é obrigatório mandar foto", "não tenho foto", "precisa de foto", "sem foto pode",
      "não consigo mandar foto"]),
    ("faq:utzig:in-person", "Posso levar o carro pessoalmente?",
     "Pode sim. O Wilian avalia o carro na Utzig e passa valor e prazo.",
     ["posso ir aí", "levo o carro aí", "prefiro ir pessoalmente", "avaliação presencial",
      "posso passar aí"]),
    ("faq:utzig:quote-by-photo", "Dá pra fazer orçamento só pela foto?",
     "A foto ajuda a ter uma ideia, mas valor e prazo a Utzig confirma depois da avaliação.",
     ["orçamento por foto", "consegue ver pela foto", "pela foto dá o preço",
      "avaliação por foto", "só pela imagem"]),
    ("faq:utzig:next-steps", "E agora, o que acontece?",
     "O Wilian recebe seu pedido e continua o atendimento por aqui para combinar avaliação, "
     "valor e agenda.",
     ["e agora", "qual o próximo passo", "o que acontece agora", "quando vão me chamar",
      "e depois"]),
]


def _edge(eid, source, target, relation, primary=False):
    metadata = {"active": True, "graph_json_edge_id": eid}
    if primary:
        metadata["primary"] = True
    return {"id": eid, "source": source, "target": target, "relation_type": relation,
            "weight": 1.0, "metadata": metadata}


def build() -> dict:
    bundle = load_active_bundle("utzig-garage")
    active = dict(bundle["metadata"]["baseline_publication"])
    nodes = {node["id"]: node for node in bundle["nodes"]}

    # Tone and persona: read by the reply model on every turn.
    tone = nodes["tone:consultative"]
    tone["summary"] = (
        "Linguagem jovem, clara e humana, com uma pergunta útil por turno e sem pressão "
        "comercial. " + STYLE + " " + NAMING
    )
    tone["data"]["avoid"] = list(dict.fromkeys([
        *tone["data"].get("avoid", []), "mensagens longas", "repetir resumo", "emoji em toda mensagem",
    ]))
    policy = nodes["persona:utzig-garage"]["data"]["conversation_policy"]
    policy["post_qualification_support"] = {"transition": CLOSING}
    policy["qualification"]["completion_message"] = COMPLETION

    # Script: drop the redundant objective question; previous procedure optional.
    for node in bundle["nodes"]:
        qualification = (node.get("data") or {}).get("qualification")
        if not isinstance(qualification, dict) or not isinstance(qualification.get("fields"), list):
            continue
        fields = [f for f in qualification["fields"] if not (isinstance(f, dict) and f.get("key") == "objective")]
        for field in fields:
            if isinstance(field, dict) and field.get("key") == "procedimento_anterior":
                field["required"] = False
        qualification["fields"] = fields
        if isinstance(qualification.get("required_fields"), list):
            qualification["required_fields"] = [
                key for key in qualification["required_fields"]
                if key not in {"objective", "procedimento_anterior"}
            ]

    # Shorter photo FAQ and new photo / visit FAQs.
    nodes["faq:photos"]["data"]["answer"] = (
        "Pode sim. As fotos ajudam a adiantar a avaliação, mas não substituem a "
        "avaliação do Wilian."
    )
    nodes["faq:photos"]["summary"] = nodes["faq:photos"]["data"]["answer"]
    for fid, question, answer, aliases in NEW_FAQS:
        bundle["nodes"].append({
            "id": fid, "node_type": "faq", "slug": fid.replace(":", "-"), "status": "approved",
            "title": question, "summary": answer, "tags": [],
            "data": {
                "question": question, "answer": answer,
                "question_aliases": aliases, "aliases": aliases,
                "claims": [{"claim_type": "public_information", "evidence_node_ids": [fid],
                            "policy": {"mode": "informational"}}],
                "capabilities": {"global_context": True},
                "graph_json_node_id": fid, "source": SOURCE, "validation_status": "approved",
            },
        })
        bundle["edges"] += [
            _edge(f"edge:{fid}:contains", GLOBAL_PARENT, fid, "contains", True),
            _edge(f"edge:{fid}:answers", GLOBAL_PARENT, fid, "answers_question"),
            _edge(f"edge:{fid}:embedded", fid, EMBEDDED, "publishes_to"),
        ]

    metadata = bundle["metadata"]
    metadata["purpose"] = "Utzig v17: shorter human messages, light closing with photo tip"
    metadata["source"] = SOURCE
    metadata["baseline_publication"] = dict(active)
    metadata["publication_allowed"] = True
    return bundle


def main() -> int:
    bundle = build()
    BUNDLE_FILE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle_nodes": len(bundle["nodes"]), "bundle_edges": len(bundle["edges"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
