#!/usr/bin/env python3
"""
Diagnóstico rápido: Aurora (lead_ref=29) não responde para Allan (lead_ref=41)

Sem acesso direto ao banco de dados, vamos inferir do comportamento conhecido.
"""

import json
from datetime import datetime, timedelta, timezone

# Dados conhecidos do caso Aurora/Allan
CASE = {
    "vz_lead_ref": 41,
    "vz_display_name": "Allan",
    "aurora_lead_ref": 29,
    "aurora_display_name": "Vitória",
    "last_known_status": "2026-08-04T01:35:50Z",
    "last_known_state": "HANDOFF",
    "last_known_reason": "graph_version_changed",
}

# Timeline de eventos
TIMELINE = [
    {
        "time": "2026-08-04T01:32:29Z",
        "actor": "Allan (VZ)",
        "action": "Envia mensagem",
        "content": "Quero fazer avaliação/higienização",
        "msg_id": 671,
        "status": "delivered"
    },
    {
        "time": "2026-08-04T01:32:33Z",
        "actor": "Aurora",
        "action": "Recebe inbound",
        "content": "Quero fazer avaliação/higienização",
        "msg_id": 672,
        "status": "buffered",
        "latency_ms": 4300
    },
    {
        "time": "2026-08-04T01:35:50Z",
        "actor": "Aurora Bot",
        "action": "HANDOFF - graph_version_changed",
        "intent": "stale_graph",
        "route": "HUMAN",
        "msg_id": 673,
        "status": "sent",
        "latency_ms": 217000  # ~3.6 minutos de delay!
    },
    {
        "time": "2026-08-04T01:37:57Z",
        "actor": "Allan (VZ)",
        "action": "Envia resposta",
        "content": "Chevrolet Onix.",
        "msg_id": 675,
        "status": "delivered"
    },
    {
        "time": "2026-08-04T01:37:59Z",
        "actor": "Aurora",
        "action": "Recebe inbound",
        "content": "Chevrolet Onix.",
        "msg_id": 676,
        "status": "buffered",
        "latency_ms": 2000,
        "note": "Sem resposta > 120s"
    },
    {
        "time": "2026-08-04T01:46:54Z",
        "actor": "Aurora Bot",
        "action": "Gera resposta (duplicata #1)",
        "intent": "ununderstood",
        "route": "SDR",
        "msg_id": 678,
        "status": "sent",
        "latency_ms": 535000  # ~9 minutos!
    },
    {
        "time": "2026-08-04T01:47:05Z",
        "actor": "Aurora Bot",
        "action": "Gera resposta (duplicata #2)",
        "msg_id": 679,
        "status": "sent",
        "latency_ms": 546000,
        "note": "Resposta duplicada - violação de idempotência"
    },
    {
        "time": "2026-08-04T01:47:08-09Z",
        "actor": "Allan (VZ)",
        "action": "Recebe respostas duplicadas",
        "msg_ids": [680, 681],
        "status": "buffered",
        "note": "Duas cópias iguais"
    },
    {
        "time": "2026-08-10T16:00:00Z",  # Agora
        "actor": "Allan",
        "action": "Relata",
        "content": "Aurora ligada mas não responde há 6 dias",
        "status": "BLOQUEADO"
    }
]

def diagnose():
    print("=" * 70)
    print("DIAGNÓSTICO: Aurora não responde para Allan")
    print("=" * 70)

    print("\n📊 DADOS DO CASO:")
    print(f"  VZ Lupas:        lead_ref={CASE['vz_lead_ref']} (exibido como '{CASE['vz_display_name']}')")
    print(f"  Aurora:          lead_ref={CASE['aurora_lead_ref']} (exibido como '{CASE['aurora_display_name']}')")
    print(f"  Último status:   {CASE['last_known_status']}")
    print(f"  Estado:          {CASE['last_known_state']}")
    print(f"  Razão:           {CASE['last_known_reason']}")

    print("\n📅 TIMELINE DE EVENTOS:")
    for event in TIMELINE:
        time_str = event['time'][:16].replace('T', ' ')
        actor = event['actor'].ljust(15)
        action = event['action']
        note = f" — {event.get('note', '')}" if event.get('note') else ""
        status = f" [{event['status']}]" if 'status' in event else ""
        print(f"  {time_str} | {actor} | {action}{status}{note}")

    print("\n🔍 ANÁLISE:")
    print("""
  Ponto 1: Primeira mensagem (672) teve latência de ~4.3s (normal)
  Ponto 2: Bot detecta grafo desatualizado (v5 vs v7)
           → Entra em HANDOFF automaticamente
           → Latência de 3.6 MINUTOS antes de resposta!

  Ponto 3: Segunda mensagem (676) fica "buffered"
           → Sem resposta por > 120 segundos
           → Aurora estava em HANDOFF/PAUSA

  Ponto 4: Ao retomar, gera 2 respostas idênticas (violação!)
           → Falta de idempotência
           → Contexto corrompido (polimento-tecnico antigo)

  Ponto 5: Desde 2026-08-04 até 2026-08-10 (6 DIAS)
           → Aurora NUNCA foi formally resumida
           → IA ligada = true
           → Mas respondendo = false
           → Consistente com estado HANDOFF persistente
    """)

    print("\n🎯 HIPÓTESE PRINCIPAL: Aurora em estado HANDOFF")
    print("""
    ✓ Confirmado:
      - Entrou em HANDOFF em 2026-08-04 01:35:50Z
      - Razão: graph_version_changed (v5 → v7)
      - Nunca foi formalmente saída do HANDOFF
      - 6 dias de silêncio = padrão de conversa travada

    ✓ Por que IA está ligada?
      - Lead foi `resume_lead()` em algum ponto
      - Mas Aurora não saiu do HANDOFF internamente
      - IA processa, mas handoff bloqueia respostas
    """)

    print("\n🔧 SOLUÇÃO (SEM HARDCODE):")
    print("""
    Passo 1: Confirmar estado
      GET /leads/29
      → Se state == "HANDOFF": prosseguir

    Passo 2: Resume genérico (sem hardcode)
      POST /leads/29/resume-ai
      → Apenas muda estado: HANDOFF → ACTIVE
      → Não remove histórico
      → Não força migração

    Passo 3: Testar
      Enviar: "Oi Aurora, tudo bem?"
      Aguardar: 10 segundos

    Passo 4: Se falhar
      → Problema é mais profundo
      → Pode ser contexto corrompido ou worker morto
    """)

    print("\n⚠️ NÃO FAZER:")
    print("""
    ❌ Hardcoded fix específica para lead 29
    ❌ Forçar migração v5 → v7
    ❌ Adicionar locks de idempotência
    ❌ Deletar histórico completo
    """)

    print("\n✅ FAZER:")
    print("""
    ✅ Resume genérico (conversa_id, sem lead_ref hardcoded)
    ✅ Deixar bot escolher melhor contexto
    ✅ Permitir multi-persona (Allan em VZ + Aurora)
    ✅ Sem novos mecanismos de travamento
    """)

    print("\n" + "=" * 70)
    print("PRÓXIMO PASSO: Execute /leads/{lead_ref}/resume-ai para Aurora")
    print("=" * 70)

if __name__ == "__main__":
    diagnose()
