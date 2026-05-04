#!/usr/bin/env python3
"""
E2E: Shopify Instant Cards Validation.

Testa o gatilho automatico do crawler Shopify e a geracao imediata de 
proposed_entries (cards) no chatbot ao fornecer uma URL Shopify.
"""
import os
import json
import argparse
from datetime import datetime, timezone
from urllib import parse, request, error
from typing import Any

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
CATALOG_URL = "https://tockfatal.com/pages/catalogo-modal"
PERSONA_SLUG = "tock-fatal"

class TestFailure(Exception):
    pass

def http_json(method: str, path: str, body: dict = None) -> Any:
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        raise TestFailure(f"{method} {path} -> {e.code}: {e.read().decode()}")

def main():
    print(f"\n== E2E Shopify Instant Cards [{datetime.now().isoformat()}] ==")
    
    # 1. Start Session com Contexto de URL e Blocos
    # Simulando o que o front-end envia ao clicar em 'Iniciar' com Produto marcado
    initial_context = (
        f"fonte principal: {CATALOG_URL}\n"
        "## Blocos de conhecimento solicitados\n"
        "- product: extrair produtos do site"
    )
    
    print(f"Iniciando sessao para {PERSONA_SLUG}...")
    session_resp = http_json("POST", "/kb-intake/start", body={
        "persona_slug": PERSONA_SLUG,
        "agent_key": "sofia",
        "initial_context": initial_context
    })
    
    session_id = session_resp.get("session_id")
    if not session_id:
        raise TestFailure("Falha ao criar sessao")
    
    # 2. Enviar primeira mensagem (Gatilho Auto-Crawl)
    print("Enviando sinal de inicio ('Oi')...")
    chat_resp = http_json("POST", "/kb-intake/message", body={
        "session_id": session_id,
        "message": "Oi, pode começar a extração."
    })
    
    # 3. Validar se o Crawler foi ativado via Shopify Tool
    crawler = chat_resp.get("crawler")
    if not crawler:
        raise TestFailure("Crawler nao foi disparado automaticamente")
    
    print(f"Confianca do Crawler: {crawler.get('confidence')} ({crawler.get('confidence_label')})")
    
    shopify_stage = next((s for s in crawler.get("stages", []) if s["key"] == "shopify"), None)
    if not shopify_stage or shopify_stage["status"] != "done":
        print("AVISO: Tool Shopify nao detectou API. Verifique a URL.")
    else:
        print("Sucesso: Tool Shopify detectou e extraiu produtos via JSON.")

    # 4. Validar se os cards (proposed_entries) estao presentes
    entries = chat_resp.get("proposed_entries", [])
    print(f"Total de cards propostos: {len(entries)}")
    
    products = [e for e in entries if e.get("content_type") == "product"]
    
    if len(products) < 2:
        # Se a Sofia seguiu a regra de "gerar pelo menos 3", esperamos mais, 
        # mas o requisito do teste sao os 2 visiveis no Shopify.
        raise TestFailure(f"Esperava pelo menos 2 cards de produto, recebeu {len(products)}")

    print("\nCards de Produto detectados:")
    for p in products:
        title = p.get("title")
        status = p.get("status")
        print(f" - [Card] {title} ({status})")
        
    # Validação de conteúdo básico dos cards
    for p in products:
        if not p.get("slug") or not p.get("content"):
            raise TestFailure(f"Card de produto {p.get('title')} incompleto (sem slug ou conteudo)")

    # 5. Salvar reporte
    report = {
        "session_id": session_id,
        "crawler_confidence": crawler.get("confidence"),
        "n_proposed_cards": len(entries),
        "products": [p.get("title") for p in products]
    }
    
    os.makedirs("test-artifacts", exist_ok=True)
    with open("test-artifacts/e2e_shopify_instant_cards.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nPASS: Teste concluido com sucesso. Reporte salvo em test-artifacts.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nFAIL: {e}")
        exit(1)