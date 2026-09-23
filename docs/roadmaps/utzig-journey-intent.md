# Utzig Garage: jornada de intenção do veículo

Status: candidata GraphBundle v6, ainda não publicada.

## Decisão

A pergunta antiga — “O que você espera melhorar ou preservar no veículo?” —
misturava o resultado técnico desejado com o motivo comercial da conversa. A
pergunta candidata preserva a apresentação consultiva aprovada pelo operador,
mas mede uma dimensão diferente:

> Só pra eu entender melhor: a ideia é preparar o carro pra venda ou é pra
> manter ele bem cuidado?

Não se usa “uso próprio”: ela sugere uma categoria de posse, e não o motivo da
jornada. “Cuidado contínuo” cobre conservar, proteger e manter o carro; não
pressupõe quanto tempo o cliente ficará com ele nem exclui outros usos.

O identificador técnico continua `objective` para manter compatibilidade com
proof, commits e conversas iniciadas na publicação anterior. Seu contrato passa
a declarar `semantic_type=vehicle_journey_intent`; o valor persistido preserva
as palavras do cliente, em vez de forçar uma enumeração. Há uma pergunta, não
duas.

## Mapa no grafo

```text
Utzig Garage
├─ Campanha: Preparação para venda
│  └─ Audiência: Preparar para venda
│     ├─ mesmo tópico → Revitalização
│     └─ mesmo tópico → Aprimoramento
└─ Campanha: Cuidado contínuo
   └─ Audiência: Cuidado contínuo
      ├─ mesmo tópico → Preservação
      └─ mesmo tópico → Aprimoramento
```

Os vínculos com grupos são `same_topic_as`, não vínculos de catálogo. Assim, a
escolha de um serviço não classifica automaticamente a pessoa como alguém que
vai vender ou manter o carro. A classificação vem apenas de `audience_signal`
com trecho literal da resposta, é verificada no proof e só é persistida depois
do commit atômico. As duas audiências são contexto global, portanto seus IDs e
critérios ficam disponíveis em qualquer serviço.

A formulação conversacional foi autorizada pelo operador após comparação com o
padrão de atendimento da Aurora. Não foram reutilizados prompt de sistema,
serviços, regras comerciais, credenciais ou políticas da Aurora.

## Evidência de candidato

- Base ativa v5: `ab38794a-0580-4bd0-afe7-df6fcb7a0e58`, checksum
  `sha256:af58d99ac5f3a9ba9afcf3918c18e22b7791ab71021662f442b9c82385c93a33`.
- Candidato: draft
  `sha256:c49a006b96ee60f25124f95bc699795be5c22c57c8c181660b4687b35a585bef`; runtime
  `sha256:589991eaa28e510b9f3a67851ead4a1adf521f679d897890c85c170e4e3fe8af`.
- Validações concluídas: JSON, compilação `graph-compiler-v3.6.5`,
  `git diff --check` e 9 testes focados de GraphBundle/publisher.
- Próximo gate: stage contra export autenticado da v5 e uma única sessão WA
  Validator interna com respostas diferentes da redação/examples deste grafo.
  Não houve ativação nem WhatsApp real nesta etapa.
