"""Build Tock Fatal v17: conversational sales qualification and retrieval.

The candidate is content-only. It adds persona-owned customer identity,
purchase-readiness and fulfillment fields; rewrites technical catalog language;
publishes operational/photo FAQs; and makes AI identity plus pre-handoff notice
explicit in graph-owned tone/rules. It does not publish or activate anything.

Usage:
    python api/scripts/build_tock_fatal_v17.py <v16-bundle> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any


BASELINE_PURPOSE = "tock_fatal_v16_voice_reachable"
SOURCE = "operator_conversation_review_2026-09-05"
PERSONA = "persona:tock-fatal"
QUALIFICATION_CAMPAIGN = "campaign:tock-whatsapp-qualification"
CATALOG_CAMPAIGN = "campaign:tock-catalogo-produtos"
EMBED = "embed:tock-default"


def _node_index(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in bundle.get("nodes") or []}


def _edge(
    source: str, target: str, relation_type: str, *, suffix: str = ""
) -> dict[str, Any]:
    return {
        "id": f"edge:v17:{source}:{target}:{relation_type}{suffix}",
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "metadata": {"source": SOURCE},
    }


def _qualification_faq(
    node_id: str, *, slug: str, title: str, question: str, field_key: str
) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_type": "faq",
        "slug": slug,
        "title": title,
        "summary": question,
        "tags": ["qualificacao", "vendas", field_key],
        "status": "approved",
        "data": {
            "question": question,
            "role": "qualification_question",
            "field_key": field_key,
            "source": SOURCE,
            "source_node_id": PERSONA,
            "source_node_type": "persona",
            "branch_path": [PERSONA, QUALIFICATION_CAMPAIGN, node_id],
            "status": "approved",
            "capabilities": {"global_context": True},
        },
    }


def _faq(
    node_id: str,
    *,
    slug: str,
    title: str,
    question: str,
    answer: str,
    aliases: list[str],
    source_node_id: str = QUALIFICATION_CAMPAIGN,
    source_node_type: str = "campaign",
    branch_path: list[str] | None = None,
    media_availability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "question": question,
        "question_aliases": aliases,
        "answer": answer,
        "source": SOURCE,
        "source_node_id": source_node_id,
        "source_node_type": source_node_type,
        "branch_path": branch_path or [PERSONA, QUALIFICATION_CAMPAIGN, node_id],
        "status": "approved",
        "capabilities": {"global_context": True},
        "claims": [{
            "claim_type": "service_detail",
            "policy": "published_accumulated_faq",
            "evidence_node_ids": [node_id],
        }],
        "metadata": {
            "role": "knowledge_faq",
            "generator": "tock_conversation_faqs_v2",
            "intent": slug,
            "accumulated_at_publication": True,
        },
    }
    if media_availability:
        data["media_availability"] = media_availability
    return {
        "id": node_id,
        "node_type": "faq",
        "slug": slug,
        "title": title,
        "summary": answer,
        "tags": ["faq", "atendimento", "retrieval"],
        "status": "approved",
        "data": data,
    }


def _global_faqs() -> list[dict[str, Any]]:
    return [
        _faq(
            "faq:tock-ai-identity",
            slug="ai-identity",
            title="Quem é a Vitória?",
            question="Estou falando com uma pessoa?",
            aliases=["você é robô", "você é uma ia", "quem está falando", "é atendimento automático"],
            answer=(
                "Eu sou a Vitória, assistente virtual com inteligência artificial da Tock Fatal. "
                "Posso ajudar a conhecer as peças e organizar seu interesse; quando for preciso, "
                "aviso antes de chamar uma pessoa da equipe."
            ),
        ),
        _faq(
            "faq:tock-human-attendant",
            slug="human-attendant",
            title="Falar com um atendente",
            question="Posso falar com um atendente?",
            aliases=["quero falar com uma pessoa", "me passa para o atendimento", "preciso de ajuda humana"],
            answer="Claro. Vou avisar que uma pessoa da equipe continuará o atendimento com você.",
        ),
        _faq(
            "faq:tock-handoff-notice",
            slug="handoff-notice",
            title="Aviso antes do encaminhamento",
            question="Como vou saber que o atendimento será encaminhado?",
            aliases=["você vai me transferir", "quem continua o atendimento", "vai chamar alguém"],
            answer=(
                "Eu sempre aviso antes do encaminhamento. Depois desse aviso, uma pessoa da equipe "
                "continua o atendimento com as informações que você já passou."
            ),
        ),
        _faq(
            "faq:tock-shipping",
            slug="shipping",
            title="Envio do pedido",
            question="Vocês fazem envio?",
            aliases=["vocês entregam", "manda para minha cidade", "tem entrega", "preciso de frete"],
            answer=(
                "Posso registrar que você precisa de envio. O frete e o prazo dependem do destino e "
                "do pedido, por isso um especialista confirma essas informações antes de fechar."
            ),
        ),
        _faq(
            "faq:tock-freight-value",
            slug="freight-value",
            title="Confirmação do valor do frete",
            question="Quanto fica o frete?",
            aliases=["qual o valor da entrega", "frete para minha cidade", "quanto custa enviar"],
            answer=(
                "O valor do frete precisa ser confirmado por um especialista conforme o destino e "
                "o pedido. Vou registrar essa necessidade para a continuidade do atendimento."
            ),
        ),
        _faq(
            "faq:tock-store-visit",
            slug="store-visit",
            title="Visita à loja física",
            question="Posso visitar a loja física?",
            aliases=["quero ir na loja", "posso ver pessoalmente", "tem loja física", "prefiro buscar"],
            answer=(
                "Posso registrar que você prefere visitar a loja física. Uma pessoa da equipe confirma "
                "o endereço, o horário e a disponibilidade para a visita antes de você se deslocar."
            ),
        ),
        _faq(
            "faq:tock-payment-confirmation",
            slug="payment-confirmation",
            title="Formas de pagamento",
            question="Quais são as formas de pagamento?",
            aliases=["como posso pagar", "parcela", "aceita pix", "aceita cartão"],
            answer=(
                "Uma pessoa da equipe confirma as formas e condições de pagamento disponíveis antes "
                "de fechar o pedido."
            ),
        ),
        _faq(
            "faq:tock-stock-confirmation",
            slug="stock-confirmation",
            title="Confirmação de estoque",
            question="Tem essa peça em estoque?",
            aliases=["está disponível", "tem pronta entrega", "ainda tem", "posso comprar agora"],
            answer=(
                "Posso te ajudar com as informações publicadas da peça. A disponibilidade atual é "
                "confirmada por uma pessoa da equipe antes do pedido."
            ),
        ),
        _faq(
            "faq:tock-variations-confirmation",
            slug="variations-confirmation",
            title="Confirmação de cor e tamanho",
            question="Tem outra cor ou tamanho?",
            aliases=["quais cores tem", "tem meu tamanho", "tem variação", "outras opções"],
            answer=(
                "Eu explico as cores e tamanhos que estiverem publicados para a peça. A equipe "
                "confirma a disponibilidade da variação escolhida antes do pedido."
            ),
        ),
        _faq(
            "faq:tock-order-next-step",
            slug="order-next-step",
            title="Próximo passo do pedido",
            question="Como faço para continuar a compra?",
            aliases=["quero fechar", "quero comprar", "como faço o pedido", "qual o próximo passo"],
            answer=(
                "Eu organizo o que você procura e aviso antes de encaminhar. Depois, uma pessoa da "
                "equipe confirma estoque, pagamento e, se necessário, frete."
            ),
        ),
        _faq(
            "faq:tock-photo-unavailable",
            slug="photo-unavailable",
            title="Foto não disponível para envio automático",
            question="Você pode me mandar uma foto dessa peça?",
            aliases=["tem foto", "manda uma imagem", "quero ver a peça", "me mostra uma foto"],
            answer=(
                "Quando não houver uma foto aprovada dessa peça, vou solicitar que um atendente "
                "continue e envie uma foto. Se você também precisar de frete, ele poderá confirmar o valor."
            ),
        ),
    ]


def _approved_product_photo_faqs(
    bundle: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    nodes = _node_index(bundle)
    parents: dict[str, str] = {
        str(edge.get("target")): str(edge.get("source"))
        for edge in bundle.get("edges") or []
        if edge.get("relation_type") == "contains"
    }
    result: list[tuple[str, dict[str, Any]]] = []
    for asset in bundle.get("nodes") or []:
        data = asset.get("data") or {}
        media = data.get("media") or {}
        product_id = str(data.get("product_node_id") or "")
        if (
            asset.get("node_type") != "asset"
            or asset.get("status") not in {"approved", "validated", "active"}
            or data.get("asset_role") != "primary_product_media"
            or media.get("kind") != "image"
            or product_id not in nodes
        ):
            continue
        product = nodes[product_id]
        faq_id = f"faq:{product['slug']}-approved-photo"
        path = [product_id]
        cursor = product_id
        seen: set[str] = set()
        while cursor in parents and cursor not in seen:
            seen.add(cursor)
            cursor = parents[cursor]
            path.insert(0, cursor)
        if path[0] != PERSONA:
            path.insert(0, PERSONA)
        path.append(faq_id)
        faq = _faq(
            faq_id,
            slug=f"{product['slug']}-approved-photo",
            title=f"Foto aprovada — {product['title']}",
            question=f"Tem foto de {product['title']}?",
            aliases=[
                f"manda foto de {product['title']}",
                f"quero ver {product['title']}",
                f"tem imagem de {product['title']}",
            ],
            answer=(
                f"Há uma foto aprovada de {product['title']}. Posso solicitar o envio dessa foto "
                "para você."
            ),
            source_node_id=str(asset["id"]),
            source_node_type="asset",
            branch_path=path,
            media_availability={
                "status": "approved",
                "product_node_id": product_id,
                "asset_node_id": str(asset["id"]),
                "media_kind": "image",
                "sha256": str(media.get("sha256") or ""),
            },
        )
        result.append((product_id, faq))
    return result


def _render_tone(node: dict[str, Any]) -> None:
    data = node.get("data") or {}
    voice = data.get("voice") or {}
    guidelines = voice.get("guidelines") or data.get("guidelines") or []
    style = voice.get("style") or []
    lines = [f"## {node['title']}", str(node.get("summary") or "")]
    if style:
        lines.append("Tom: " + ", ".join(str(item) for item in style) + ".")
    if guidelines:
        lines.append("Como falar:")
        lines.extend(f"- {item}" for item in guidelines)
    data["markdown"] = "\n".join(line for line in lines if line).strip()
    node["data"] = data


def _render_handoff(node: dict[str, Any]) -> None:
    data = node.get("data") or {}
    rule = data.get("handoff_rule") or {}
    lines = [
        f"## {node['title']}",
        str(node.get("summary") or ""),
        "Antes de qualquer encaminhamento conversacional, avise claramente que uma pessoa da equipe continuará.",
        "Nunca encerre em silêncio e nunca confirme frete, estoque, pagamento ou prazo sem validação humana.",
    ]
    if rule.get("text"):
        lines.append(f"Aviso publicado: \"{rule['text']}\"")
    data["markdown"] = "\n".join(line for line in lines if line).strip()
    node["data"] = data


def _rewrite_navigation(node: dict[str, Any]) -> bool:
    if node.get("node_type") != "faq" or not str(node.get("id") or "").endswith("-navegacao"):
        return False
    data = node.get("data") or {}
    answer = str(data.get("answer") or "")
    rewritten = re.sub(
        r"^No grupo (.+?), as opções publicadas são:",
        r"Entre as opções de \1, temos:",
        answer,
    )
    if rewritten == answer:
        return False
    data["answer"] = rewritten
    node["summary"] = rewritten
    return True


def _assert_baseline(bundle: dict[str, Any]) -> None:
    if (bundle.get("persona") or {}).get("slug") != "tock-fatal":
        raise ValueError("the baseline is not the Tock Fatal bundle")
    if (bundle.get("metadata") or {}).get("purpose") != BASELINE_PURPOSE:
        raise ValueError(f"expected {BASELINE_PURPOSE!r} baseline")
    nodes = _node_index(bundle)
    for required in (PERSONA, QUALIFICATION_CAMPAIGN, CATALOG_CAMPAIGN, EMBED):
        if required not in nodes:
            raise ValueError(f"baseline is missing {required}")


def build(source: dict[str, Any]) -> dict[str, Any]:
    _assert_baseline(source)
    candidate = copy.deepcopy(source)
    nodes = _node_index(candidate)

    persona = nodes[PERSONA]
    pdata = persona.setdefault("data", {})
    policy = pdata.setdefault("conversation_policy", {})
    policy["opening"] = {
        **(policy.get("opening") or {}),
        "self_introduction_required_on_first_reply": True,
        "self_introduction_identity": "Vitória, assistente virtual com inteligência artificial da Tock Fatal",
        "introduction_precedes_all_other_first_reply_content": True,
        "first_reply_required_elements": [
            "nome_vitoria",
            "assistente_virtual_com_inteligencia_artificial",
            "tock_fatal",
        ],
        "request_customer_name": "once_after_purchase_profile_is_understood",
        "customer_name_required_before_help": False,
    }
    policy["question_policy"] = {
        **(policy.get("question_policy") or {}),
        "current_turn_facts_precede_question": True,
        "never_ask_field_answered_in_current_message": True,
        "question_must_target_eligible_missing_field": True,
        "asked_field_key_required_for_qualification_question": True,
        "branch_selection_question_forbidden_after_profile_understood": True,
        "after_purchase_profile_when_name_missing": "ask_nome_cliente_before_any_other_question",
        "catalog_navigation_question_forbidden_until_name_resolved_or_already_asked": True,
        "never_repeat_nome_cliente_after_branch_switch": True,
        "preferred_field_order_after_purchase_profile": [
            "nome_cliente",
            "grau_qualificacao",
            "forma_recebimento",
        ],
        "instructions": [
            "Antes de formular uma pergunta, considere todos os fatos extraídos da mensagem atual e os fatos já conhecidos.",
            "Nunca pergunte novamente o perfil de compra quando a pessoa já disse uso próprio, varejo, atacado ou revenda.",
            "Depois de entender o perfil de compra, pergunte o nome uma única vez se ele ainda não for conhecido nem tiver sido perguntado.",
            "No primeiro turno da assistente, apresente-se como Vitória, assistente virtual com inteligência artificial da Tock Fatal antes de qualquer outro conteúdo.",
            "Se o perfil de compra acabou de ser entendido e nome_cliente ainda não foi perguntado nem conhecido, a única pergunta permitida é nome_cliente com asked_field_key igual a nome_cliente.",
            "Se nome_cliente já foi perguntado, não o pergunte novamente após uma correção ou troca de perfil; reconheça a mudança sem repetir a pergunta.",
            "Quando nome_cliente for a resposta esperada, frases como meu nome é X, pode me chamar de X, sou X ou apenas X informam o nome. Extraia nome_cliente como known usando somente o nome como value e um trecho literal da mensagem como evidence_span.",
            "Se a resposta pública usar o nome informado, o mesmo turno deve obrigatoriamente persistir nome_cliente; nunca cumprimente a pessoa pelo nome deixando esse fato fora de facts.",
            "Toda pergunta de qualificação deve tratar de um campo ainda elegível e informar esse campo em asked_field_key.",
        ],
    }
    policy["sales_routing"] = {
        "selector_kind": "purchase_profile",
        "service_selector_enabled": False,
        "customer_facing_terms": ["uso próprio", "revenda", "peça", "categoria"],
        "forbidden_customer_facing_terms": ["serviço", "grupo de produtos", "branch", "node", "retrieval"],
    }
    policy["handoff"] = {
        "pre_notice_required": True,
        "notice": "Vou avisar uma pessoa da equipe para continuar o atendimento com você.",
        "preserve_collected_facts": True,
        "silent_handoff_forbidden": True,
    }
    policy["content_delivery"] = {
        **(policy.get("content_delivery") or {}),
        "selection_mode": "approved_asset_evidence_only",
        "offer_only_when_exact_product_has_approved_asset": True,
        "do_not_repeat_offer": True,
        "without_approved_asset": {
            "mention_only_after_explicit_photo_request": True,
            "action": "handoff_with_pre_notice",
            "response": (
                "Vou solicitar que um atendente continue e envie uma foto dessa peça. "
                "Se você também precisar de frete, ele poderá confirmar o valor."
            ),
        },
    }
    policy["qualification"] = {
        **(policy.get("qualification") or {}),
        "name_question_max_attempts": 1,
        "persist_every_fact_in_current_message": True,
        "sales_readiness_field": "grau_qualificacao",
        "fulfillment_field": "forma_recebimento",
    }
    policy.setdefault("field_labels", {}).update({
        "nome_cliente": "seu nome",
        "grau_qualificacao": "momento da compra",
        "forma_recebimento": "preferência de envio ou visita",
    })
    pdata["qualification"] = {
        "fields": [
            {
                "key": "nome_cliente",
                "question_node_id": "faq:tock-customer-name",
                "required": True,
                "owner_node_id": PERSONA,
                "scope": "persona",
                "accepted_statuses": ["known"],
                "depends_on": ["purchase_profile"],
                "priority": 1.0,
                "overwrite_policy": "explicit_correction",
                "value_schema": {"type": "string", "minLength": 1},
                "validation": {
                    "mode": "semantic",
                    "semantic_type": "human_full_name",
                    "description": "Primeiro nome ou nome informado pela pessoa, inclusive em frases como pode me chamar de X, meu nome é X, sou X ou em uma resposta curta contendo somente o nome.",
                    "extraction_required_when_expected": True,
                    "acknowledgement_requires_fact": True,
                    # The conversation envelope v3 does not expose a confidence
                    # property for facts. The runtime therefore receives 0.0;
                    # keeping this at 0.9 silently demoted valid answers such as
                    # "Pode me chamar de Beatriz" after the model had already
                    # used the name in its public reply. Literal evidence and the
                    # human-name shape remain required by the proof layer.
                    "model_confidence_min": 0.0,
                    "min_tokens": 1,
                    "max_tokens": 6,
                    "confirmation_policy": "last_resort",
                },
            },
            {
                "key": "grau_qualificacao",
                "question_node_id": "faq:tock-sales-readiness",
                "required": True,
                "owner_node_id": PERSONA,
                "scope": "persona",
                "accepted_statuses": ["known", "unknown"],
                "depends_on": ["purchase_profile", "nome_cliente"],
                "priority": 0.8,
                "overwrite_policy": "explicit_correction",
                "validation": {
                    "mode": "enum",
                    "values": [
                        {"value": "conhecendo", "aliases": ["só olhando", "conhecendo", "pesquisando"]},
                        {"value": "comparando", "aliases": ["comparando", "vendo opções", "decidindo"]},
                        {"value": "pronto_para_avancar", "aliases": ["quero comprar", "quero fechar", "pode avançar"]},
                    ],
                },
            },
            {
                "key": "forma_recebimento",
                "question_node_id": "faq:tock-fulfillment-preference",
                "required": True,
                "owner_node_id": PERSONA,
                "scope": "persona",
                "accepted_statuses": ["known", "unknown"],
                "depends_on": ["purchase_profile", "nome_cliente"],
                "priority": 0.7,
                "overwrite_policy": "explicit_correction",
                "validation": {
                    "mode": "enum",
                    "values": [
                        {"value": "envio", "aliases": ["envio", "entrega", "frete", "receber em casa"]},
                        {"value": "visita_loja", "aliases": ["ir à loja", "visitar", "buscar", "ver pessoalmente"]},
                        {"value": "a_definir", "aliases": ["não sei", "vou decidir", "tanto faz"]},
                    ],
                },
            },
        ]
    }

    # The name cannot drift to the end: branch-specific qualification only
    # becomes eligible after the persona-owned name has been captured once.
    for anchor in ("audience:tock-retail", "audience:tock-reseller"):
        fields = ((nodes[anchor].get("data") or {}).get("qualification") or {}).get("fields") or []
        for field in fields:
            if field.get("key") == "purchase_profile":
                continue
            dependencies = [str(value) for value in field.get("depends_on") or []]
            if "nome_cliente" not in dependencies:
                dependencies.append("nome_cliente")
            field["depends_on"] = dependencies

    qualification_nodes = [
        _qualification_faq(
            "faq:tock-customer-name",
            slug="customer-name",
            title="Nome da pessoa",
            question="Como você prefere que eu te chame?",
            field_key="nome_cliente",
        ),
        _qualification_faq(
            "faq:tock-sales-readiness",
            slug="sales-readiness",
            title="Momento da compra",
            question="Você está conhecendo as opções, comparando ou já quer avançar com a compra?",
            field_key="grau_qualificacao",
        ),
        _qualification_faq(
            "faq:tock-fulfillment-preference",
            slug="fulfillment-preference",
            title="Preferência de recebimento",
            question="Você prefere receber por envio ou visitar a loja física?",
            field_key="forma_recebimento",
        ),
    ]

    additions: list[tuple[str, dict[str, Any]]] = [
        *((QUALIFICATION_CAMPAIGN, node) for node in qualification_nodes),
        *((QUALIFICATION_CAMPAIGN, node) for node in _global_faqs()),
        *_approved_product_photo_faqs(candidate),
    ]
    existing_ids = set(nodes)
    for parent, node in additions:
        if node["id"] in existing_ids:
            raise ValueError(f"baseline already contains {node['id']}")
        candidate["nodes"].append(node)
        candidate["edges"].append(_edge(parent, node["id"], "contains"))
        candidate["edges"].append(_edge(node["id"], EMBED, "publishes_to"))
        existing_ids.add(node["id"])

    greetings = set(policy.get("intents", {}).get("greeting", {}).get("response_node_ids") or [])
    for node in candidate["nodes"]:
        if node.get("id") in greetings:
            answer = (
                "Oi! Eu sou a Vitória, assistente virtual com inteligência artificial da Tock Fatal. "
                "Como posso te ajudar?"
            )
            node["summary"] = answer
            node.setdefault("data", {})["answer"] = answer
            node["data"]["source"] = SOURCE
        _rewrite_navigation(node)

    voice = nodes["tone:tock-vitoria-voice"]
    voice["summary"] = (
        "Vitória é a assistente virtual com inteligência artificial da Tock Fatal. "
        "Ela se apresenta no primeiro contato e conversa com delicadeza, clareza e naturalidade."
    )
    voice_guidelines = voice.setdefault("data", {}).setdefault("voice", {}).setdefault("guidelines", [])
    voice_guidelines.extend([
        "No primeiro contato, apresente-se como Vitória, assistente virtual com inteligência artificial da Tock Fatal; não repita a apresentação depois.",
        "Use o nome da pessoa depois que ela informar, mas pergunte esse nome apenas uma vez.",
        "Não repita uma descrição, uma lista de peças ou uma oferta de foto já enviada na conversa.",
        "Nunca diga grupo de produtos, opções publicadas, branch, node, retrieval ou serviço para se referir a uma categoria de roupas.",
        "Se houver evidência de foto aprovada para a peça exata, você pode oferecer ajuda para mostrar essa foto uma única vez.",
        "Sem evidência de foto aprovada, só mencione foto se a pessoa pedir; avise que um atendente poderá continuar e enviar uma imagem.",
        "Frete e prazo de envio são confirmados por um especialista; não estime nem confirme valores.",
    ])
    voice["data"]["source"] = SOURCE
    _render_tone(voice)

    clear = nodes["tone:tock-vitoria-clear-language"]
    clear_guidelines = clear.setdefault("data", {}).setdefault("guidelines", [])
    clear_guidelines.extend([
        "Fale como uma agente de atendimento, não como a interface do grafo.",
        "Faça transições suaves: reconheça a escolha, acrescente uma informação nova e só então faça uma pergunta útil.",
        "Se a resposta nova seria apenas uma repetição, não repita; avance para outro assunto elegível ou encaminhe com aviso.",
    ])
    clear["data"]["source"] = SOURCE
    _render_tone(clear)

    handoff = nodes["rule:tock-safe-handoff"]
    handoff["summary"] = (
        "Vitória avisa antes de encaminhar e preserva o que a pessoa já informou. "
        "A equipe confirma frete, estoque, pagamento, prazo e fotos não disponíveis no atendimento automático."
    )
    handoff_data = handoff.setdefault("data", {})
    handoff_data["handoff_rule"] = {
        "condition": "qualification_complete_or_human_confirmation_required",
        "pre_notice_required": True,
        "text": "Vou avisar uma pessoa da equipe para continuar o atendimento com você.",
        "silent_handoff_forbidden": True,
    }
    handoff_data["handoff_message"] = handoff_data["handoff_rule"]["text"]
    handoff_data["source"] = SOURCE
    _render_handoff(handoff)

    candidate["metadata"] = {
        **(candidate.get("metadata") or {}),
        "purpose": "tock_fatal_v17_sales_conversation_repair",
        "content_revision": "3.6-sales-conversation-repair",
        "source": SOURCE,
        "publication_allowed": True,
        "change_summary": (
            "Nome persona-owned perguntado uma vez, grau de qualificação e envio/visita; "
            "identidade de IA, aviso pré-handoff, linguagem não técnica, 11 FAQ operacionais "
            "e FAQ de mídia somente para os quatro produtos com asset aprovado."
        ),
        "conversation_regressions": [
            "ai_introduction_first_turn_only",
            "customer_name_asked_once",
            "sales_no_service_selector",
            "sales_readiness_and_fulfillment",
            "pre_handoff_notice",
            "no_repeated_information_or_photo_offer",
            "approved_photo_offer_only",
            "unapproved_photo_human_followup_only_on_request",
            "freight_requires_specialist_confirmation",
        ],
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
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    print(f"  nodes {len(source['nodes'])} -> {len(candidate['nodes'])}")
    print(f"  edges {len(source['edges'])} -> {len(candidate['edges'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
