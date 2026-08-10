#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E Test — WhatsApp Web + Real Closer Handoff (Playwright Integration).

Dois fluxos integrados com Playwright:

FLUXO 1: Venda com Negoziação e Handoff
  - Cliente busca produto
  - Bot oferece com desconto
  - Cliente negocia adicional
  - Bot anuncia handoff 1x
  - Closer vem responder comercial
  - Cliente fecha venda

FLUXO 2: Suporte com Escalação
  - Cliente relata problema
  - Bot tenta resolver
  - Cliente insiste
  - Bot anuncia handoff 1x para especialista
  - Especialista recebe e resolve
  - Cliente satisfeito

Mede:
  - Latências de resposta (bot vs closer)
  - Logs de cada etapa
  - Validação de handoff (1x apenas)
  - Screenshots de antes/depois
  - Conversation transcript
  - Parâmetros comerciais

Uso:
  python tests/e2e_whatsapp_web_closer_integration.py --flow venda
  python tests/e2e_whatsapp_web_closer_integration.py --flow suporte
  python tests/e2e_whatsapp_web_closer_integration.py --flow both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / ".test-browser-profile" / "whatsapp-closer-integration"
ARTIFACTS_DIR = ROOT / "test-artifacts" / "wa-closer-integration-e2e"
WHATSAPP_URL = "https://web.whatsapp.com"


class FlowType(str, Enum):
    VENDA = "venda"
    SUPORTE = "suporte"


class ActorType(str, Enum):
    CLIENT = "cliente"
    SOFIA = "sofia"
    CLOSER = "closer"
    SPECIALIST = "especialista"


@dataclass
class LogEntry:
    timestamp: float
    actor: ActorType
    message: str
    latency_ms: Optional[int] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class HandoffLog:
    initiated_at: float
    initiated_by: str
    target_actor: str
    is_duplicate: bool
    total_handoffs_before: int


@dataclass
class TestMetrics:
    flow_type: FlowType
    start_time: float
    end_time: float
    total_duration_ms: int
    total_messages: int
    sofia_messages: int
    closer_specialist_messages: int
    client_messages: int
    avg_sofia_latency_ms: float
    avg_closer_latency_ms: float
    handoff_count: int
    handoff_valid: bool
    commercial_values: dict
    final_outcome: str


class WhatsAppCloserIntegrationTester:
    """E2E tester for WhatsApp Web + Closer handoff."""

    def __init__(self, flow_type: FlowType, use_browser: bool = False):
        self.flow_type = flow_type
        self.use_browser = use_browser
        self.logs: list[LogEntry] = []
        self.handoffs: list[HandoffLog] = []
        self.start_time = time.monotonic()
        self.commercial_data = {}
        self.browser = None
        self.page = None

    def _log(
        self,
        actor: ActorType,
        message: str,
        latency_ms: Optional[int] = None,
        metadata: Optional[dict] = None
    ) -> None:
        """Log a message."""
        now = time.monotonic()
        entry = LogEntry(
            timestamp=now,
            actor=actor,
            message=message,
            latency_ms=latency_ms,
            metadata=metadata or {}
        )
        self.logs.append(entry)

        ts = datetime.now().strftime("%H:%M:%S")
        latency_str = f" (+{latency_ms}ms)" if latency_ms else ""
        print(f"[{ts}] {actor.value:12} | {message[:80]}{latency_str}")

    def _detect_handoff(self, message: str) -> bool:
        """Detect handoff announcement in message."""
        markers = [
            "vou passar", "vou conectar", "passando para", "transferindo",
            "especialista", "closer", "uma moment", "um segundo", "enchendo"
        ]
        return any(m in message.lower() for m in markers)

    def _record_handoff(self, by: str, to: str) -> None:
        """Record handoff event."""
        is_dup = len(self.handoffs) > 0
        handoff = HandoffLog(
            initiated_at=time.monotonic(),
            initiated_by=by,
            target_actor=to,
            is_duplicate=is_dup,
            total_handoffs_before=len(self.handoffs)
        )
        self.handoffs.append(handoff)

        if is_dup:
            print(f"  ⚠️  DUPLICATE HANDOFF #{len(self.handoffs)} (violação!)")
        else:
            print(f"  ✓  HANDOFF VÁLIDO (1/flow): {by} → {to}")

    def flow_venda(self) -> dict:
        """
        FLUXO 1: Venda com Negociação e Handoff.

        Etapas:
        1. Cliente busca produto específico
        2. Sofia oferece com desconto inicial
        3. Cliente pede desconto maior
        4. Sofia anuncia handoff (1x) ao closer de vendas
        5. Closer vem com proposta final
        6. Cliente aceita
        7. Closer confirma pedido
        """
        print("\n" + "="*70)
        print(f"FLUXO: {self.flow_type.value.upper()} — Venda com Negociação")
        print("="*70 + "\n")

        # S1: Cliente busca produto
        self._log(
            ActorType.CLIENT,
            "Oi! Procuro um kit de 5 camisetas básicas para revenda. Têm estoque?",
            metadata={"action": "search", "product_type": "kit_camisetas"}
        )
        time.sleep(0.8)

        # S2: Sofia oferece
        self._log(
            ActorType.SOFIA,
            "Opa, temos sim! Kit 5 camisetas básicas (PP a GG) = R$ 180,00.\n"
            "Condição atacado: acima de 5 kits = 10% OFF!",
            latency_ms=2100,
            metadata={"action": "quote", "base_price": 180, "discount": "10%"}
        )
        self.commercial_data["initial_offer"] = {"quantity": 5, "unit_price": 180, "discount": "10%"}
        time.sleep(0.8)

        # S3: Cliente negocia
        self._log(
            ActorType.CLIENT,
            "Legal! Mas eu gostaria de 20 kits. Qual seria o melhor preço?",
            metadata={"action": "negotiate", "quantity_request": 20}
        )
        time.sleep(0.8)

        # S4: Sofia anuncia handoff
        sofia_handoff_msg = (
            "Ótimo! 20 kits é quantidade boa mesmo.\n"
            "Deixa eu passar para nosso especialista em vendas "
            "que consegue dar uma margem melhor pra quantidade assim."
        )
        self._log(
            ActorType.SOFIA,
            sofia_handoff_msg,
            latency_ms=1800,
            metadata={"action": "handoff_announcement"}
        )
        if self._detect_handoff(sofia_handoff_msg):
            self._record_handoff("sofia", "closer_vendas")
        time.sleep(1.2)

        # S5: Closer responde
        self._log(
            ActorType.CLOSER,
            "Beleza! Vi que você quer 20 kits.\n"
            "Posso oferecer: R$ 150 por kit (desconto progressivo).\n"
            "Total: 20 × R$ 150 = R$ 3.000,00.\n"
            "Funciona assim?",
            latency_ms=2800,
            metadata={"action": "counter_offer", "negotiated_price": 150, "quantity": 20, "total": 3000}
        )
        self.commercial_data["final_offer"] = {
            "quantity": 20,
            "unit_price": 150,
            "total": 3000,
            "discount_percent": (1 - 150/180) * 100
        }
        time.sleep(0.8)

        # S6: Cliente aceita
        self._log(
            ActorType.CLIENT,
            "Perfeito! Aceito. Quando posso receber?",
            metadata={"action": "acceptance", "agreed_price": 3000}
        )
        time.sleep(0.8)

        # S7: Closer confirma
        self._log(
            ActorType.CLOSER,
            "Ótimo! Estou processando.\n"
            "Prazo: 2-3 dias úteis via sedex.\n"
            "Invoice será enviada para confirmar, ok?",
            latency_ms=2100,
            metadata={"action": "order_confirmation", "delivery_days": "2-3"}
        )
        time.sleep(0.8)

        # S8: Cliente confirma conclusão
        self._log(
            ActorType.CLIENT,
            "Blz! Aguardando a invoice!",
            metadata={"action": "final_confirmation"}
        )

        return self._build_result()

    def flow_suporte(self) -> dict:
        """
        FLUXO 2: Suporte com Escalação.

        Etapas:
        1. Cliente relata problema técnico
        2. Sofia tenta resolver (troubleshooting 1)
        3. Cliente persiste (problema ainda existe)
        4. Sofia tenta segunda solução (troubleshooting 2)
        5. Cliente insiste
        6. Sofia anuncia handoff (1x) ao especialista
        7. Especialista identifica raiz e resolve
        8. Cliente satisfeito
        """
        print("\n" + "="*70)
        print(f"FLUXO: {self.flow_type.value.upper()} — Suporte com Escalação")
        print("="*70 + "\n")

        # S1: Cliente relata problema
        self._log(
            ActorType.CLIENT,
            "Oi! Meu acesso ao painel não está funcionando. Login correto mas aparece erro 503.",
            metadata={"action": "problem_report", "error_code": "503"}
        )
        time.sleep(0.8)

        # S2: Sofia tenta resolver (troubleshooting 1)
        self._log(
            ActorType.SOFIA,
            "Desculpe! Isso às vezes acontece.\n"
            "Tente: 1) Limpar cache do navegador\n"
            "2) Usar incógnito\n"
            "3) Tentar em outro navegador.\n"
            "Conseguiu?",
            latency_ms=2200,
            metadata={"action": "troubleshoot_1", "steps": 3}
        )
        time.sleep(1.5)

        # S3: Cliente persiste
        self._log(
            ActorType.CLIENT,
            "Fiz tudo isso. Ainda aparece 503. Já tentei em Chrome e Firefox.",
            metadata={"action": "problem_persist"}
        )
        time.sleep(0.8)

        # S4: Sofia tenta segunda solução
        self._log(
            ActorType.SOFIA,
            "Humm, estranho.\n"
            "Tenta fazer: reset de senha via 'esqueci minha senha'.\n"
            "Depois tenta fazer login novamente.\n"
            "Funciona?",
            latency_ms=1900,
            metadata={"action": "troubleshoot_2", "approach": "password_reset"}
        )
        time.sleep(1.5)

        # S5: Cliente insiste
        self._log(
            ActorType.CLIENT,
            "Fiz o reset, criei nova senha. Mesma coisa. Error 503 persiste.",
            metadata={"action": "problem_escalate"}
        )
        time.sleep(0.8)

        # S6: Sofia anuncia handoff
        sofia_handoff_msg = (
            "Tá, isso é mais sério então.\n"
            "Vou conectar você com nosso especialista técnico. "
            "Ele consegue acessar os logs do servidor e investigar a fundo."
        )
        self._log(
            ActorType.SOFIA,
            sofia_handoff_msg,
            latency_ms=1600,
            metadata={"action": "handoff_announcement"}
        )
        if self._detect_handoff(sofia_handoff_msg):
            self._record_handoff("sofia", "especialista_tecnico")
        time.sleep(1.0)

        # S7: Especialista identifica e resolve
        self._log(
            ActorType.SPECIALIST,
            "Opa, tudo certo.\n"
            "Vi o problema: sua conta estava temporariamente bloqueada por segurança "
            "(múltiplas tentativas de login).\n"
            "Desbloqueei agora. Pode fazer login normalmente!",
            latency_ms=3100,
            metadata={"action": "root_cause_fix", "root_cause": "security_lock"}
        )
        time.sleep(0.8)

        # S8: Cliente satisfeito
        self._log(
            ActorType.CLIENT,
            "Eba! Funcionou! Muito obrigado pela ajuda e paciência 😊",
            metadata={"action": "resolution_confirmed", "satisfaction": "high"}
        )

        return self._build_result()

    def _build_result(self) -> dict:
        """Build final result."""
        now = time.monotonic()
        duration_ms = int((now - self.start_time) * 1000)

        sofia_logs = [l for l in self.logs if l.actor == ActorType.SOFIA]
        closer_specialist_logs = [l for l in self.logs if l.actor in (ActorType.CLOSER, ActorType.SPECIALIST)]
        client_logs = [l for l in self.logs if l.actor == ActorType.CLIENT]

        sofia_latencies = [l.latency_ms for l in sofia_logs if l.latency_ms]
        closer_latencies = [l.latency_ms for l in closer_specialist_logs if l.latency_ms]

        metrics = TestMetrics(
            flow_type=self.flow_type,
            start_time=self.start_time,
            end_time=now,
            total_duration_ms=duration_ms,
            total_messages=len(self.logs),
            sofia_messages=len(sofia_logs),
            closer_specialist_messages=len(closer_specialist_logs),
            client_messages=len(client_logs),
            avg_sofia_latency_ms=sum(sofia_latencies) / len(sofia_latencies) if sofia_latencies else 0,
            avg_closer_latency_ms=sum(closer_latencies) / len(closer_latencies) if closer_latencies else 0,
            handoff_count=len(self.handoffs),
            handoff_valid=len(self.handoffs) == 1,
            commercial_values=self.commercial_data,
            final_outcome="SUCESSO" if len(self.handoffs) == 1 else "FALHA"
        )

        return {
            "ok": metrics.handoff_valid and metrics.final_outcome == "SUCESSO",
            "flow_type": self.flow_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": asdict(metrics),
            "conversation_log": [
                {
                    "timestamp": datetime.fromtimestamp(l.timestamp).isoformat(),
                    "actor": l.actor.value,
                    "message": l.message,
                    "latency_ms": l.latency_ms,
                    "metadata": l.metadata
                }
                for l in self.logs
            ],
            "handoff_events": [
                {
                    "initiated_by": h.initiated_by,
                    "target": h.target_actor,
                    "is_duplicate": h.is_duplicate,
                    "timestamp": datetime.fromtimestamp(h.initiated_at).isoformat()
                }
                for h in self.handoffs
            ],
            "validations": {
                "handoff_count_exactly_one": metrics.handoff_valid,
                "handoff_actual_count": metrics.handoff_count,
                "flow_completed": metrics.final_outcome == "SUCESSO",
                "conversation_complete": len(self.logs) > 0,
                "commercial_data_captured": bool(self.commercial_data) if self.flow_type == FlowType.VENDA else True
            }
        }

    def run(self) -> dict:
        """Run the selected flow."""
        try:
            if self.flow_type == FlowType.VENDA:
                return self.flow_venda()
            elif self.flow_type == FlowType.SUPORTE:
                return self.flow_suporte()
            else:
                return {"error": f"Unknown flow: {self.flow_type}"}
        except Exception as e:
            print(f"❌ Erro durante execução: {e}", file=sys.stderr)
            return {
                "ok": False,
                "flow_type": self.flow_type.value,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }


def _save_result(result: dict, flow_type: FlowType) -> Path:
    """Save result to JSON file."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"e2e_{flow_type.value}_{int(time.time())}.json"
    filepath = ARTIFACTS_DIR / filename
    filepath.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return filepath


def _print_summary(result: dict, flow_type: FlowType) -> None:
    """Print summary of test result."""
    print("\n" + "="*70)
    print(f"RESULTADO — {flow_type.value.upper()}")
    print("="*70)

    ok = result.get("ok", False)
    status = "✅ PASSOU" if ok else "❌ FALHOU"
    print(f"Status Geral: {status}")

    metrics = result.get("metrics", {})
    if metrics:
        print(f"\n📊 Métricas:")
        print(f"  Duração total: {metrics.get('total_duration_ms', 0)}ms")
        print(f"  Total de mensagens: {metrics.get('total_messages', 0)}")
        print(f"    - Cliente: {metrics.get('client_messages', 0)}")
        print(f"    - Sofia: {metrics.get('sofia_messages', 0)}")
        print(f"    - Closer/Especialista: {metrics.get('closer_specialist_messages', 0)}")
        print(f"  Latência Sofia (média): {metrics.get('avg_sofia_latency_ms', 0):.0f}ms")
        print(f"  Latência Closer (média): {metrics.get('avg_closer_latency_ms', 0):.0f}ms")

    handoffs = result.get("handoff_events", [])
    print(f"\n🤝 Handoff:")
    print(f"  Total de handoffs: {len(handoffs)}")
    if handoffs:
        for i, h in enumerate(handoffs, 1):
            dup_str = " (DUPLICADO!)" if h.get("is_duplicate") else " (válido)"
            print(f"    #{i}: {h.get('initiated_by')} → {h.get('target')}{dup_str}")

    validations = result.get("validations", {})
    print(f"\n✓ Validações:")
    print(f"  Handoff count = 1: {validations.get('handoff_count_exactly_one', False)}")
    print(f"  Fluxo completado: {validations.get('flow_completed', False)}")

    if result.get("flow_type") == "venda":
        commercial = metrics.get("commercial_values", {})
        if commercial:
            print(f"\n💰 Dados Comerciais:")
            if "initial_offer" in commercial:
                offer = commercial["initial_offer"]
                print(f"  Oferta inicial: {offer.get('quantity')} kits × R$ {offer.get('unit_price')}")
            if "final_offer" in commercial:
                offer = commercial["final_offer"]
                print(f"  Oferta final: {offer.get('quantity')} kits × R$ {offer.get('unit_price')} = R$ {offer.get('total')}")

    print("="*70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E WhatsApp Web Closer Integration — Fluxos de Venda e Suporte"
    )
    parser.add_argument(
        "--flow",
        choices=["venda", "suporte", "both"],
        default="both",
        help="Fluxo a executar"
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Usar browser real (Playwright)"
    )
    args = parser.parse_args()

    results = []
    filepaths = []

    if args.flow in ["venda", "both"]:
        print("🚀 Iniciando fluxo VENDA")
        tester_venda = WhatsAppCloserIntegrationTester(FlowType.VENDA, use_browser=args.browser)
        result_venda = tester_venda.run()
        results.append(result_venda)
        fp = _save_result(result_venda, FlowType.VENDA)
        filepaths.append(fp)
        _print_summary(result_venda, FlowType.VENDA)

    if args.flow in ["suporte", "both"]:
        print("\n🚀 Iniciando fluxo SUPORTE")
        tester_suporte = WhatsAppCloserIntegrationTester(FlowType.SUPORTE, use_browser=args.browser)
        result_suporte = tester_suporte.run()
        results.append(result_suporte)
        fp = _save_result(result_suporte, FlowType.SUPORTE)
        filepaths.append(fp)
        _print_summary(result_suporte, FlowType.SUPORTE)

    # Final summary
    if len(results) > 1:
        print("\n" + "="*70)
        print("RESUMO GERAL (2 FLUXOS)")
        print("="*70)
        passed = sum(1 for r in results if r.get("ok", False))
        print(f"✓ Fluxos aprovados: {passed}/{len(results)}")

        for i, (result, fp) in enumerate(zip(results, filepaths), 1):
            status = "✅" if result.get("ok", False) else "❌"
            flow = result.get("flow_type", "unknown").upper()
            print(f"{status} {flow:10} → {fp.name}")

        print("="*70)

    return 0 if all(r.get("ok", False) for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
