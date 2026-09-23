# Handoff — Utzig Garage em produção

Data: 2026-09-23.

## Estado entregue

- Persona produtiva: `utzig-garage` (`e7b7b2e8-859e-4185-b675-79bc0f3d846e`).
- GraphBundle v2 ativo; checksum runtime:
  `sha256:6ded5d383b8cc455be3e937bb8e869041d7f654bbafa1d4ae3c80fa37dec14a4`.
- Contrato público `GET /api/menu/utzig-garage` responde com `landing_page`,
  duas rotas, tema, 12 serviços, três audiências, assets derivados e sem a
  faixa comercial interna.
- Site publicado e validado em navegador:
  `https://utzig.vercel.app/` e
  `https://utzig.vercel.app/estetica-automotiva`.
- Card-pio: commit `4ee9573` aceita corretamente assets de blocos graph-backed
  sem `id` legado e aplica estilo MapLibre padrão quando o grafo não declara
  um override. Deploy Vercel: `dpl_7AMyepVBgVGif6dnpdR4RmhmZHnY`.
- O número público de agendamento é o binding ativo transferido de Aurora;
  o canal humano permanece separado, para o Alemão. Não registrar nem exibir
  identificadores internos de Meta como `wa.me`.

## Estado do binding e risco atual

- O binding Meta Cloud ativo foi movido de Aurora para Utzig pelo workflow de
  reassignment após dry-run, sem leads a destacar e sem WhatsApp real.
- A execução usa o caminho agentic do runtime. O WA Validator interno da Utzig
  falhou na sessão `d355b182-a940-48f3-8df1-a0cec388db3f`: o inbound sintético
  foi terminalizado como `dead_letter` porque o transport não persistiu o
  resultado canônico. Não houve proof nem outbound.
- Evidências: Actions `35819254223` (validação) e `35819369863` (inspeção).
- Não repetir o validador em modo `run` nem enviar mensagem real até localizar
  a falha de runtime/configuração e testar a correção com o sink interno.

## Próxima sessão — ordem segura

1. Executar somente auditoria read-only do binding Utzig, integração de modelo
   por persona e eventos do buffer sintético; preservar Aurora, leads e
   histórico.
2. Confirmar a causa do `dead_letter` no transport/conversation-runtime e
   corrigir apenas o serviço proprietário, com teste proporcional.
3. Fazer candidate isolado, cutover blue/green e rollback automático conforme
   o manifesto, sem migration e sem Docker local.
4. Rodar WA Validator interno uma única vez. Exigir decisão canônica, proof,
   commit e no máximo um outbound interno por inbound.
5. Só após `technical_pass=true` e `quality_pass=true`, registrar a evidência
   de produção e considerar o atendimento automático aprovado.

## Segurança e repositórios

- O primeiro relatório de reassignment expôs material sensível do binding em
  log privado. A execução foi removida e o redaction foi versionado em Brain
  (`2572a67`). Tratar a credencial do provedor como candidata a rotação.
- Brain e Card-pio estavam limpos e alinhados a `origin/main` antes deste
  handoff; este arquivo deve ser versionado agora.
