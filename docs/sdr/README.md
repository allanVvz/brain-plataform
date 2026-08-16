# Documentos canônicos de atendimento

Cada persona possui uma pasta em `docs/sdr/<persona-slug>/`. O frontmatter
estruturado e o corpo Markdown são a única fonte editorial de fatos comerciais.
O publicador compila os documentos para Graph JSON v2 e só então projeta o
conteúdo nas tabelas de conhecimento existentes.

Estrutura esperada:

- `persona.md`, `brand.md`, `campaign.md` e `catalog.md`;
- `agents/*.md`, `briefings/*.md`, `tone/*.md` e `rules/*.md`;
- `products/*.md`, `copy/*.md` e `faq/*.md`;
- `sources/*.md`, com a evidência original e os checksums da migração.

Documentos publicáveis precisam declarar `persona`, `type`, `slug`, `title`,
`source`, `status`, `tags`, `metadata` e `relations`. Somente conteúdo
`validated`/`approved` e ativo pode ser compilado para uso dos agentes.

Metadados internos ficam no frontmatter e não devem ser copiados para o texto
público.

`campaign.md` declara `metadata.campaign_type` com o formato de apresentacao
(`menu`, `catalog`). O eixo `metadata.offering_kind` (`product` | `service`),
que decide como o agente qualifica, esta no roadmap — ver "Produto e servico"
em `docs/knowledge-flow.md`.
