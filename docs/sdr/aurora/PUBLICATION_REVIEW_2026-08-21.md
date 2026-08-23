# Revisão de publicação — Lia/Aurora — 2026-08-21

Disposition: `awaiting_legacy_publication`

## Autoridade e dívida técnica

Esta entrega usa o publicador legado `publish_aurora_graph.py`. A migração da
Aurora para GraphBundle permanece dívida técnica explícita do item 6 do roadmap.
Nenhum bundle Aurora foi criado e o backend/n8n não recebeu regra de negócio.

## Baseline produtivo

| Artefato | Versão | Checksum | Contagem |
|---|---:|---|---|
| Graph JSON legado ativo | 8 | `sha256:b058a6fefac568da31ce66dbbe11cd87454e20bd26b0b71247f4afc5fc322ba0` | 92 nodes / 178 edges |
| Publicação v3 ativa | 67 | `sha256:bb40f955211c4a3173531faac17177e4a2dd794827ba4d6f8b9146021ea46b40` | 90 entries / 2.343 chunks |

## Candidato local puro

| Artefato | Checksum | Contagem |
|---|---|---|
| Graph JSON 2.1 canônico | `sha256:97fd66ab04d9618ef99dd7cb0ec99a6d8a7a8f117e658e66dbc76dbf5bd9def6` | 153 nodes / 234 edges |
| Documento compilado v3.6.2 | `sha256:f40a29b5b8fdc8373948b7e281c0f96e8487084d8e92e81ae9ec367d70bc1b40` | 14 branches / 30 FAQs elegíveis |
| Fixture em disco | `sha256:80e66e5909ca67d6a8e920fa4743f4d172bba442925850459e431aa928d37ade` | JSON de autoria |
| Corpus humano | `sha256:0b7db4cf1672298a5814189ea3f6157fd62394697a851956578a3813219dee08` | 55 entradas / 5 aliases cada |

O checksum canônico difere do hash do arquivo porque o pipeline atualiza o
Graph JSON 2.0 para 2.1, materializa nodes de pergunta e renderiza Markdown de
forma determinística antes da publicação.

## Diff semântico

- Campos comuns reduzidos para `nome_cliente` e `servico`.
- Perguntas graph-owned adicionadas para todos os campos específicos.
- 12 produtos ativos no catálogo, incluindo lavagem técnica do motor/cofre.
- 14 branches totais quando somados atendimento humano e reclamação.
- 13 nodes sem sustentação documental ficam `archived`, sem exclusão.
- Claims de proteção UV de faróis foram removidos.
- `espelhamento`, `pintura opaca` e `melhorar brilho` viraram aliases de
  polimento técnico.
- 53 FAQs realmente novas entram `pending_validation`; duas entradas do corpus
  foram consolidadas em FAQs preexistentes para evitar slug/resposta duplicados.
- Nenhuma FAQ pendente recebe `publishes_to` para o Embedded.
- 87 nodes ficam aprovados, 53 pendentes e 13 arquivados; 84 grants ativos.

## Contratos afetados

- Higienização passa a perguntar revestimento dos bancos e uso em estrada de
  chão, além de objetivo, avaliação, modelo, ano e condição.
- Polimento técnico/comercial passa a perguntar procedimento anterior, foco em
  brilho/riscos e cor.
- Lavagem de motor/cofre pergunta vazamento de óleo, estrada de chão, modelo,
  ano e condição.
- Pintura/chapeação registram rota presencial/remota; a solicitação de mídia
  continua instrução de rota porque o fast lane não suporta campo condicional.

## Validação local

- `70 passed` no gate focado, incluindo o contrato de materialização das
  perguntas e as suítes Aurora.
- Graph JSON 2.1 válido.
- Todas as chaves obrigatórias possuem pergunta não vazia no node Persona.
- 53 FAQs pendentes com exatamente cinco aliases e zero grant ao Embedded.
- Isolamento: apenas `persona_slug=aurora`; nenhum arquivo Tock Fatal alterado.

## Sequência autorizada

1. Deploy do SHA contendo fixture, docs e testes, mantendo o binding como está
   por decisão explícita do operador durante a fase de teste.
2. Publicar Graph JSON legado com CAS `expected-version=8` e `--skip-v3`.
3. Revisar versão 9 e checksum materializado.
4. Ativação/compilação v3 permanece separada; executar somente após autorização
   explícita adicional.
5. Após ativação, validar apenas pelo WA Validator direto.
