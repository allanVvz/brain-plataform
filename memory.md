# Brain Platform Memory

Updated: 2026-08-12

## Estado final comprovado

- Produção é o único ambiente operacional desta frente. Não usar Docker local
  nem QA.
- Release atual: `8462cc0075441eccdc38a3801ca0806d7ab2bd8c`.
- CI `31591050956` e deploy produtivo `31591536760` concluíram com sucesso.
- API e worker executam a mesma imagem imutável do release atual. `/health`
  respondeu `status=ok` e `workers_embedded=false` após o deploy.
- O dashboard do mesmo push está `Ready` na Vercel em produção.
- Não houve migration nem limpeza neste release.

## Autoridade de pausa e handoff

- A toggle `IA ativa` no eyebrow da conversa é a única autoridade operacional
  para pausa e handoff.
- O estado canônico é por lead: `handoff_level` e `ai_paused`.
- O gate global `personas.config.portal.automation_mode` foi removido do worker,
  dos contratos da API e das telas de configuração.
- As rotas globais `/portal/personas/{slug}/automation` foram removidas.
- A chave legada `portal.automation_mode=human_only` foi removida da persona
  Aurora em produção de forma transacional (`UPDATE 1`).
- O helper frontend que corrigia handoff apenas localmente foi removido; a UI
  agora reflete o estado persistido pelo backend.

## Aurora

- Persona: `96e0d69f-9abd-406a-bbb9-3e7977f24ec8`.
- Binding: `6386bc58-ade9-44c4-9211-0f59f23ffca5`.
- Binding ativo, Meta Cloud conectado e `metadata.safety_paused=false`.
- Lead 87 (Allan): `handoff_level=none`, `ai_paused=false`; a toggle deve mostrar
  IA ativa e novos inbounds são elegíveis para processamento.
- Lead 135 (Allan): `handoff_level=full`, `ai_paused=true`; permanece em handoff
  por decisão da toggle daquele lead.
- Oito inbounds antigos do lead 87 continuam em `waiting_human`, incluindo três
  saudações de 2026-08-12. Foram preservados para evitar respostas tardias em
  WhatsApp real. Nenhuma mensagem foi reenfileirada ou enviada nesta correção.
- A ação explícita de reativar a toggle de um lead pausado usa `resume_lead` e
  reenfileira os inbounds `waiting_human` desse lead.

## Validação do patch

- Testes backend focados: 72 aprovados.
- `py_compile`, `git diff --check`, verificação anti-hardcode e build Next.js:
  aprovados.
- O teste do worker prova que uma configuração legada `human_only` não bloqueia
  um lead cuja toggle está ativa.
- O teste de contrato prova a ausência das rotas globais de automação.
- Nenhum teste foi skipado por esta alteração; etapas de CI sem relação com o
  diff foram omitidas pelo filtro de escopo.

## Regra conversacional preservada

- Uma pergunta pendente pode ser publicada no máximo duas vezes.
- Na interação seguinte sem resposta válida, o campo é persistido como
  `unknown`/não respondido e não volta a ser perguntado.
- O campo continua pendente e pode ser preenchido espontaneamente depois,
  substituindo `unknown` por `known` quando o valor satisfaz o schema publicado.

## Restrições permanentes

- Auditoria read-only e dry-run antes de qualquer mutação produtiva.
- Não executar limpeza, migration ou novo deploy sem necessidade e autorização.
- WA Validator somente direto/interno; não usar WhatsApp real como teste.
- Preservar bindings, filas e clientes reais salvo autorização operacional
  explícita e alvo previamente auditado.
