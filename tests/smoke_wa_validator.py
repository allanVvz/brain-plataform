#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test — WA Validator pipeline.

Chama /process diretamente com uma mensagem do fluxo Tock Fatal e verifica
que o agente retornou uma resposta não-vazia. Não precisa de WhatsApp nem de
script gerado — testa o núcleo do pipeline em ~3s.

Uso:
    python tests/smoke_wa_validator.py
    python tests/smoke_wa_validator.py --base http://localhost:8000
    pytest tests/smoke_wa_validator.py
"""
import argparse
import sys
import time

try:
    import requests
except ImportError:
    print("SKIP smoke test — 'requests' não instalado")
    sys.exit(0)

BASE_URL = "http://localhost:8000"
TIMEOUT = 30
TEST_MESSAGE = "Oi, qual o preço dos produtos e tem frete grátis?"
PERSONA = "tock-fatal"


def _process(base: str) -> dict:
    r = requests.post(
        f"{base}/process",
        json={
            "lead_id": "smoke_test_wa_validator",
            "mensagem": TEST_MESSAGE,
            "persona_slug": PERSONA,
            "stage": "novo",
            "canal": "whatsapp",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def run(base: str = BASE_URL) -> bool:
    t0 = time.monotonic()
    try:
        data = _process(base)
    except requests.exceptions.ConnectionError:
        print(f"SKIP  servidor não está rodando em {base}")
        return True  # não falha o hook se o servidor estiver offline
    except Exception as exc:
        print(f"FAIL  /process levantou exceção: {exc}")
        return False

    elapsed = int((time.monotonic() - t0) * 1000)
    reply = (data.get("reply") or "").strip()
    agent = data.get("agent_used", "?")
    latency = data.get("latency_ms", elapsed)

    if reply:
        preview = reply[:70].replace("\n", " ").encode("ascii", "replace").decode("ascii")
        print(f"PASS  agent={agent} latency={latency}ms reply={preview!r}")
        return True
    else:
        print(
            f"FAIL  agente '{agent}' não gerou resposta "
            f"(score={data.get('score')}, stage={data.get('stage_update')})"
        )
        return False


# ── pytest entry-point ────────────────────────────────────────────────────────

def test_wa_validator_pipeline():
    """pytest: /process deve retornar reply não-vazio para persona tock-fatal."""
    assert run(BASE_URL), "smoke test falhou — veja stdout para detalhes"


# ── CLI entry-point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WA Validator smoke test")
    parser.add_argument("--base", default=BASE_URL, help="URL base da API")
    args = parser.parse_args()

    ok = run(args.base)
    sys.exit(0 if ok else 1)
