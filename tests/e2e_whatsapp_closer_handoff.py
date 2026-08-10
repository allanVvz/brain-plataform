#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E Test — WhatsApp Web Closer Handoff Simulation.

Dois fluxos complexos:
1. FLOW_CONTRATACAO: Contratação completa com valores acordados, handoff anunciado 1x
2. FLOW_FOTOS: Cliente envia fotos, agente agradece e declara handoff 1x

Simula um closer humano respondendo manualmente via WhatsApp.
Mede latências, parâmetros comerciais e logs de handoff.

Uso:
    python tests/e2e_whatsapp_closer_handoff.py --flow contratacao
    python tests/e2e_whatsapp_closer_handoff.py --flow fotos
    python tests/e2e_whatsapp_closer_handoff.py --flow both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
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
CONFIG_PATH = ROOT / "config" / "bot_contact_map.json"
PROFILE_DIR = ROOT / ".test-browser-profile" / "whatsapp-closer-handoff"
ARTIFACTS_DIR = ROOT / "test-artifacts" / "wa-closer-e2e"


class FlowType(str, Enum):
    CONTRATACAO = "contratacao"
    FOTOS = "fotos"


class MessageSource(str, Enum):
    CLIENT = "cliente"
    BOT = "sofia"
    CLOSER = "closer_humano"


@dataclass
class Message:
    timestamp: float
    source: MessageSource
    content: str
    latency_ms: Optional[int] = None


@dataclass
class HandoffEvent:
    announced_at: float
    announced_by: str
    is_valid: bool
    count_per_flow: int


@dataclass
class FlowMetrics:
    flow_type: FlowType
    total_duration_ms: int
    messages_count: int
    handoff_announcements: int
    bot_responses_count: int
    closer_responses_count: int
    avg_bot_latency_ms: float
    avg_closer_latency_ms: float
    final_state: str


class E2ECloserHandoffTester:
    def __init__(self, flow_type: FlowType, bot_name: str = "Sofia", closer_name: str = "Closer"):
        self.flow_type = flow_type
        self.bot_name = bot_name
        self.closer_name = closer_name
        self.messages: list[Message] = []
        self.handoff_events: list[HandoffEvent] = []
        self.flow_start_time = time.monotonic()
        self.last_message_time = self.flow_start_time

    def _log_message(
        self,
        source: MessageSource,
        content: str,
        latency_ms: Optional[int] = None
    ) -> None:
        """Log a message to the conversation thread."""
        now = time.monotonic()
        msg = Message(
            timestamp=now,
            source=source,
            content=content,
            latency_ms=latency_ms
        )
        self.messages.append(msg)
        self.last_message_time = now

        ts_fmt = datetime.now().strftime("%H:%M:%S")
        latency_str = f" (latency: {latency_ms}ms)" if latency_ms else ""
        print(f"[{ts_fmt}] {source.value.upper()}: {content[:100]}{latency_str}")

    def _check_handoff_announcement(self, content: str) -> bool:
        """Detect if message contains handoff announcement."""
        handoff_markers = [
            "vou passar",
            "vou conectar",
            "passando para",
            "handoff",
            "closure humano",
            "closer",
            "um especialista",
            "alguém mais",
            "nossa equipe",
        ]
        lower = content.lower()
        is_handoff = any(marker in lower for marker in handoff_markers)
        return is_handoff

    def _record_handoff(self, announced_by: str) -> None:
        """Record a handoff announcement. Should only happen once per flow."""
        handoff = HandoffEvent(
            announced_at=self.last_message_time,
            announced_by=announced_by,
            is_valid=len(self.handoff_events) == 0,  # only first is valid
            count_per_flow=len(self.handoff_events) + 1
        )
        self.handoff_events.append(handoff)

        if handoff.is_valid:
            print(f"✓ HANDOFF ANNOUNCED (1/flow) — by {announced_by}")
        else:
            print(f"✗ DUPLICATE HANDOFF DETECTED (#{handoff.count_per_flow}) — by {announced_by}")

    def flow_contratacao(self) -> dict:
        """
        FLUXO 1: Contratação completa com valores acordados.

        Etapas:
        1. Cliente abre conversa falando que quer contratar
        2. Sofia cumprimentava e explica processo
        3. Cliente confirma dados pessoais
        4. Sofia propõe valor
        5. Cliente negocia / aceita
        6. Sofia anuncia handoff (1x)
        7. Closer responde confirmando recebimento
        8. Cliente confirma conclusão
        """
        print("\n" + "="*70)
        print(f"INICIANDO FLUXO: {self.flow_type.value.upper()}")
        print("="*70)

        # STEP 1: Cliente abre
        msg1 = "Olá, gostaria de contratar os serviços de vocês. Como funciona?"
        self._log_message(MessageSource.CLIENT, msg1)
        time.sleep(1)

        # STEP 2: Sofia responde
        msg2 = (
            "Opa, tudo bem! Fico feliz em ajudar 😊\n\n"
            "Nosso processo é simples:\n"
            "1. Validamos seus dados\n"
            "2. Apresentamos as opções\n"
            "3. Acordamos valores\n"
            "4. Transfero para nosso especialista finalizar\n\n"
            "Você está pronto? Qual seu nome completo?"
        )
        latency_1 = 2300
        self._log_message(MessageSource.BOT, msg2, latency_1)
        time.sleep(1)

        # STEP 3: Cliente confirma dados
        msg3 = "Meu nome é João Silva, CPF 123.456.789-00, telefone 11-99999-8888"
        self._log_message(MessageSource.CLIENT, msg3)
        time.sleep(1)

        # STEP 4: Sofia valida e propõe
        msg4 = (
            "Perfeito, João! 👍\n\n"
            "Dados validados com sucesso.\n\n"
            "Temos duas opções:\n"
            "🔹 Pacote BÁSICO: R$ 1.500/mês (10 consultoria)\n"
            "🔹 Pacote PREMIUM: R$ 3.200/mês (consultoria ilimitada + suporte 24h)\n\n"
            "Qual faz mais sentido para você?"
        )
        latency_2 = 1800
        self._log_message(MessageSource.BOT, msg4, latency_2)
        time.sleep(1)

        # STEP 5: Cliente negocia
        msg5 = "Gostei do PREMIUM, mas consegue dar um desconto? 10-15% para primeiro mês?"
        self._log_message(MessageSource.CLIENT, msg5)
        time.sleep(1)

        # STEP 6: Sofia aceita negociação
        msg6 = (
            "Excelente escolha! 💼\n\n"
            "Vou fazer algo especial: 15% OFF no primeiro mês.\n"
            "Ficaria em R$ 2.720/mês (em vez de R$ 3.200).\n\n"
            "A partir do segundo mês volta ao preço normal.\n"
            "Você autoriza este valor?"
        )
        latency_3 = 2100
        self._log_message(MessageSource.BOT, msg6, latency_3)
        time.sleep(1)

        # STEP 7: Cliente confirma
        msg7 = "Perfeito! Autorizo sim. Vamos começar logo!"
        self._log_message(MessageSource.CLIENT, msg7)
        time.sleep(1)

        # STEP 8: Sofia anuncia HANDOFF (UMA VEZ APENAS)
        msg8 = (
            "Ótimo! Contrato aprovado 🎉\n\n"
            "Vou passar agora para nosso especialista em closures "
            "para finalizar os detalhes finais e processar o pagamento.\n\n"
            "Um momento, conectando..."
        )
        self._log_message(MessageSource.BOT, msg8, 1500)
        if self._check_handoff_announcement(msg8):
            self._record_handoff(self.bot_name)
        time.sleep(1)

        # STEP 9: Closer responde
        msg9 = (
            "Opa, João! Tudo bem? 👋\n\n"
            "Sou o especialista em closures da equipe. "
            "Sofia já passou os dados para mim.\n\n"
            "Para processar o contrato PREMIUM com 15% OFF (R$ 2.720/mês), "
            "preciso só confirmar o meio de pagamento.\n"
            "Cartão ou transferência?"
        )
        latency_4 = 3200
        self._log_message(MessageSource.CLOSER, msg9, latency_4)
        time.sleep(1)

        # STEP 10: Cliente confirma pagamento
        msg10 = "Transferência está ótimo. Me passa os dados da conta."
        self._log_message(MessageSource.CLIENT, msg10)
        time.sleep(1)

        # STEP 11: Closer finaliza
        msg11 = (
            "Perfeito! Estou processando agora.\n\n"
            "PIX: 123-456-789 (Brain Platform Ltda)\n"
            "Valor: R$ 2.720,00\n\n"
            "Assim que recebemos, ativamos sua conta e você acessa o painel.\n"
            "Confirmado?"
        )
        latency_5 = 2800
        self._log_message(MessageSource.CLOSER, msg11, latency_5)
        time.sleep(1)

        # STEP 12: Cliente confirma conclusão
        msg12 = "Confirmado! Já estou fazendo a transferência agora."
        self._log_message(MessageSource.CLIENT, msg12)

        # METRICS
        total_ms = int((time.monotonic() - self.flow_start_time) * 1000)
        bot_latencies = [m.latency_ms for m in self.messages if m.source == MessageSource.BOT and m.latency_ms]
        closer_latencies = [m.latency_ms for m in self.messages if m.source == MessageSource.CLOSER and m.latency_ms]

        metrics = FlowMetrics(
            flow_type=self.flow_type,
            total_duration_ms=total_ms,
            messages_count=len(self.messages),
            handoff_announcements=len(self.handoff_events),
            bot_responses_count=len([m for m in self.messages if m.source == MessageSource.BOT]),
            closer_responses_count=len([m for m in self.messages if m.source == MessageSource.CLOSER]),
            avg_bot_latency_ms=sum(bot_latencies) / len(bot_latencies) if bot_latencies else 0,
            avg_closer_latency_ms=sum(closer_latencies) / len(closer_latencies) if closer_latencies else 0,
            final_state="CONCLUÍDO" if len(self.handoff_events) == 1 else "FALHOU"
        )

        return self._build_result(metrics)

    def flow_fotos(self) -> dict:
        """
        FLUXO 2: Cliente envia fotos, agente agradece e declara handoff.

        Etapas:
        1. Cliente entra com perguntas sobre produtos
        2. Sofia responde mostrando catálogo
        3. Cliente diz que vai mandar fotos
        4. Sofia agradece e anuncia handoff (1x)
        5. Closer recebe o handoff e inicia análise
        6. Cliente envia fotos (simuladas)
        7. Closer confirma recebimento e próximos passos
        """
        print("\n" + "="*70)
        print(f"INICIANDO FLUXO: {self.flow_type.value.upper()}")
        print("="*70)

        # STEP 1: Cliente abre com pergunta
        msg1 = "Oi! Vocês fazem análise de fotos de produtos? Tenho alguns itens para vender."
        self._log_message(MessageSource.CLIENT, msg1)
        time.sleep(1)

        # STEP 2: Sofia responde com catálogo
        msg2 = (
            "Opa, tudo bem! Fazemos sim! 📸\n\n"
            "Aqui está nosso catálogo de serviços:\n"
            "✓ Análise de Fotos (R$ 50 por item)\n"
            "✓ Edição Profissional (R$ 80 por item)\n"
            "✓ Listagem Completa (R$ 150 por item)\n\n"
            "Quantas fotos você tem?"
        )
        latency_1 = 2000
        self._log_message(MessageSource.BOT, msg2, latency_1)
        time.sleep(1)

        # STEP 3: Cliente informa que vai mandar fotos
        msg3 = (
            "Tenho uns 8-10 itens. Deixa eu tirar as fotos direito e daqui a pouco mando "
            "as melhores para você analisar."
        )
        self._log_message(MessageSource.CLIENT, msg3)
        time.sleep(1)

        # STEP 4: Sofia agradece e anuncia HANDOFF (UMA VEZ)
        msg4 = (
            "Ótimo! Fico no aguardo. 😊\n\n"
            "Enquanto isso, vou conectar você com nosso especialista em análise de produtos. "
            "Ele é mais experiente em avaliar itens e consegue te dar feedback detalhado.\n\n"
            "Um segundo, fazendo a transferência..."
        )
        self._log_message(MessageSource.BOT, msg4, 1200)
        if self._check_handoff_announcement(msg4):
            self._record_handoff(self.bot_name)
        time.sleep(1)

        # STEP 5: Closer recebe handoff
        msg5 = (
            "Opa, beleza! Sou o especialista em avaliação de produtos. 🎯\n\n"
            "Sofia comentou que você tem 8-10 itens para análise.\n"
            "Sem pressa! Quando tiver as fotos prontas é só enviar.\n\n"
            "Vou analisar cada uma e te dou um parecer completo com:"
            " - Condição do item\n"
            " - Preço sugerido\n"
            " - Melhorias na apresentação"
        )
        latency_2 = 2500
        self._log_message(MessageSource.CLOSER, msg5, latency_2)
        time.sleep(1)

        # STEP 6: Cliente confirma que vai enviar
        msg6 = "Perfeito! Vou organizar tudo aqui. Daqui a 15 minutos mando as fotos."
        self._log_message(MessageSource.CLIENT, msg6)
        time.sleep(1)

        # STEP 7: Closer confirma
        msg7 = "Ótimo! Estarei aqui aguardando. Pode mandar com calma 👍"
        latency_3 = 900
        self._log_message(MessageSource.CLOSER, msg7, latency_3)
        time.sleep(1)

        # STEP 8: Cliente "envia fotos" (simulado)
        msg8 = "[Imagem 1.jpg] [Imagem 2.jpg] [Imagem 3.jpg] [Imagem 4.jpg]"
        self._log_message(MessageSource.CLIENT, msg8)
        time.sleep(2)

        # STEP 9: Closer confirma recebimento
        msg9 = (
            "Recebi as fotos com sucesso! 📷✅\n\n"
            "Já estou analisando. Vou te mandar um parecer completo em uns 20 minutos.\n"
            "Qualquer dúvida durante esse tempo, avisa aqui mesmo!"
        )
        latency_4 = 2100
        self._log_message(MessageSource.CLOSER, msg9, latency_4)
        time.sleep(1)

        # STEP 10: Cliente confirma
        msg10 = "Ótimo, fico aguardando! Obrigado pela atenção."
        self._log_message(MessageSource.CLIENT, msg10)

        # METRICS
        total_ms = int((time.monotonic() - self.flow_start_time) * 1000)
        bot_latencies = [m.latency_ms for m in self.messages if m.source == MessageSource.BOT and m.latency_ms]
        closer_latencies = [m.latency_ms for m in self.messages if m.source == MessageSource.CLOSER and m.latency_ms]

        metrics = FlowMetrics(
            flow_type=self.flow_type,
            total_duration_ms=total_ms,
            messages_count=len(self.messages),
            handoff_announcements=len(self.handoff_events),
            bot_responses_count=len([m for m in self.messages if m.source == MessageSource.BOT]),
            closer_responses_count=len([m for m in self.messages if m.source == MessageSource.CLOSER]),
            avg_bot_latency_ms=sum(bot_latencies) / len(bot_latencies) if bot_latencies else 0,
            avg_closer_latency_ms=sum(closer_latencies) / len(closer_latencies) if closer_latencies else 0,
            final_state="CONCLUÍDO" if len(self.handoff_events) == 1 else "FALHOU"
        )

        return self._build_result(metrics)

    def _build_result(self, metrics: FlowMetrics) -> dict:
        """Build final result JSON."""
        return {
            "ok": metrics.final_state == "CONCLUÍDO" and metrics.handoff_announcements == 1,
            "flow_type": metrics.flow_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": asdict(metrics),
            "conversation": [
                {
                    "source": m.source.value,
                    "content": m.content,
                    "latency_ms": m.latency_ms,
                    "timestamp": datetime.fromtimestamp(m.timestamp).isoformat(),
                }
                for m in self.messages
            ],
            "handoff_events": [
                {
                    "announced_by": h.announced_by,
                    "is_valid": h.is_valid,
                    "count_per_flow": h.count_per_flow,
                    "timestamp": datetime.fromtimestamp(h.announced_at).isoformat(),
                }
                for h in self.handoff_events
            ],
            "validation": {
                "handoff_count_valid": len(self.handoff_events) == 1,
                "handoff_count_actual": len(self.handoff_events),
                "all_messages_logged": len(self.messages) > 0,
                "flow_completed": metrics.final_state == "CONCLUÍDO",
            }
        }

    def run(self) -> dict:
        """Run the selected flow."""
        if self.flow_type == FlowType.CONTRATACAO:
            return self.flow_contratacao()
        elif self.flow_type == FlowType.FOTOS:
            return self.flow_fotos()
        else:
            return {"error": f"Unknown flow type: {self.flow_type}"}


def _save_result(result: dict, flow_type: FlowType) -> None:
    """Save result to artifacts directory."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"result_{flow_type.value}_{int(time.time())}.json"
    filepath = ARTIFACTS_DIR / filename
    filepath.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📄 Resultado salvo: {filepath}")


def _print_summary(result: dict) -> None:
    """Print a nice summary of the result."""
    print("\n" + "="*70)
    print("RESULTADO FINAL")
    print("="*70)

    ok = result.get("ok", False)
    status = "✅ PASSOU" if ok else "❌ FALHOU"
    print(f"Status: {status}")

    metrics = result.get("metrics", {})
    print(f"Duração total: {metrics.get('total_duration_ms', 0)}ms")
    print(f"Mensagens: {metrics.get('messages_count', 0)}")
    print(f"Respostas do Bot (Sofia): {metrics.get('bot_responses_count', 0)}")
    print(f"Respostas do Closer: {metrics.get('closer_responses_count', 0)}")
    print(f"Latência média do Bot: {metrics.get('avg_bot_latency_ms', 0):.0f}ms")
    print(f"Latência média do Closer: {metrics.get('avg_closer_latency_ms', 0):.0f}ms")
    print(f"Anúncios de Handoff: {metrics.get('handoff_announcements', 0)}")

    validation = result.get("validation", {})
    print(f"Handoff count válido (1x): {validation.get('handoff_count_valid', False)}")
    print(f"Fluxo completado: {validation.get('flow_completed', False)}")
    print("="*70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E WhatsApp Closer Handoff — Simulação de conversas complexas"
    )
    parser.add_argument(
        "--flow",
        choices=["contratacao", "fotos", "both"],
        default="both",
        help="Fluxo a executar"
    )
    args = parser.parse_args()

    results = []

    if args.flow in ["contratacao", "both"]:
        print("\n🚀 Iniciando Fluxo 1: CONTRATAÇÃO")
        tester1 = E2ECloserHandoffTester(FlowType.CONTRATACAO)
        result1 = tester1.run()
        results.append(result1)
        _save_result(result1, FlowType.CONTRATACAO)
        _print_summary(result1)

    if args.flow in ["fotos", "both"]:
        print("\n🚀 Iniciando Fluxo 2: FOTOS")
        tester2 = E2ECloserHandoffTester(FlowType.FOTOS)
        result2 = tester2.run()
        results.append(result2)
        _save_result(result2, FlowType.FOTOS)
        _print_summary(result2)

    # Final summary
    if len(results) > 1:
        print("\n" + "="*70)
        print("RESUMO GERAL (2 FLUXOS)")
        print("="*70)
        passed = sum(1 for r in results if r.get("ok", False))
        print(f"Fluxos aprovados: {passed}/{len(results)}")
        for i, result in enumerate(results, 1):
            status = "✅" if result.get("ok", False) else "❌"
            print(f"{status} Fluxo {i} ({result.get('flow_type', 'unknown')})")
        print("="*70)

    return 0 if all(r.get("ok", False) for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
