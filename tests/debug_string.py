def llm_initial_context(run_token: str) -> str:
    return "
".join([
        "# Plano confirmado pelo operador",
        "persona_slug: tock-fatal",
        "objetivo: criar conhecimento para Tock Fatal Atacado a partir do catalogo Modal, usando crawler como evidencia bruta e validacao humana",
        f"fonte principal: CATALOG_URL",
        "saida esperada: knowledge_plan JSON + proposta markdown de arvore de conhecimento",
        "",
        "## Blocos de conhecimento solicitados",
        "- briefing: fonte, escopo, riscos do crawler e regras de validacao",
        "- audience: revendedoras e clientes finais",
        "- product: 5 produtos/cards",
        "- entity: cores, precos e kits",
        "- copy: 5 copies para atacado e varejo",
        "- faq: 5 perguntas recuperaveis sobre preco, cores e kits",
        "",
        "## Regras de teste",
        f"- use run_token: {run_token} em slugs/tags para isolar o teste",
        "- nao dependa de scraping perfeito; marque pendente_validacao quando nao souber",
        "- gere links semanticos entre marca, campanha, publicos, produtos, entidades, copies e FAQs",
    ])

print(llm_initial_context("test_token"))
