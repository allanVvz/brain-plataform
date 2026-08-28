# Handoff — auditoria dos fluxos Lia/Aurora e Tock Fatal

Data do snapshot: 2026-08-21  
Escopo: auditoria read-only de produção, diagnóstico e plano de correção  
Estado: diagnóstico concluído; nenhuma correção deste documento foi publicada  

## 1. Objetivo

Registrar o estado atual dos fluxos `allan lia aurora` e `allan tock fatal`, as
causas comprovadas das respostas incorretas, as correções propostas e os gates
necessários para a próxima sessão continuar sem refazer a investigação.

O pedido do operador foi estudar os dois fluxos em paralelo, privilegiar mudanças
de grafo/FAQs em vez de alterar o backend em construção, reduzir o comportamento
robótico da Aurora e explicar por que a Tock Fatal não responde sobre produtos.

## 2. Restrições e estado operacional

- A auditoria foi somente leitura.
- Nenhum WhatsApp real foi enviado para teste.
- Nenhum GraphBundle, FAQ, produto ou publicação foi criado/ativado.
- Nenhum workflow n8n foi ressincronizado.
- Nenhum deploy, migration, limpeza, alteração de binding ou alteração de worker foi
  executado nesta auditoria.
- Mudanças conversacionais deverão ser validadas apenas pelo WA Validator direto.
- Publicação exige `PublicationPlan` revisado e aprovação humana explícita.
- FAQs começam em `pending_validation` e só se conectam ao Embedded depois da
  aprovação de conteúdo e fonte.

O roadmap máximo (`docs/roadmaps/AGENT_ROADMAP.md`) determina que a Tock Fatal prove
o pipeline GraphBundle novo primeiro e que a Aurora migre por último. Portanto,
copiar o live atual da Tock para a Aurora seria contrário ao roadmap e uma regressão
de conteúdo. A direção segura é completar a Tock, prová-la e só depois migrar a
Aurora por shadow/checksum.

## 3. Arquitetura encontrada

Aurora e Tock Fatal não usam backends conversacionais diferentes atualmente.
Ambas usam:

- provider ativo Meta Cloud;
- `decision_owner=n8n_agents`;
- `pipeline_contract=conversation_v3`;
- `runtime_version=graph_agent_runtime_v3`;
- modelo `deepseek-v4-flash`;
- cadeia interna `context -> decide -> reconcile -> commit`, com tratamento de
  falha técnica;
- workflow n8n com 18 nodes e a mesma topologia estrutural.

A diferença de qualidade vem principalmente do conteúdo e das políticas publicadas
no grafo. Existe ainda drift semântico no `model_request`: a Aurora coincide com o
template canônico atual, enquanto a Tock apresentou uma versão de payload menor e
mais antiga na comparação semântica. A topologia é igual, mas conteúdo de node não
deve ser considerado equivalente apenas pelo wiring.

Conclusão: não criar fork de n8n nem backend por persona. Se o dry-run repetir o
drift, ressincronizar somente a Tock a partir de
`api/n8n-workflows/persona-conversation-template.json`.

## 4. Tock Fatal — estado atual e causa

### 4.1 Publicação ativa

- Graph publication: v6.
- Checksum observado: `sha256:ad330d489...`.
- Propósito declarado: `tock_fatal_internal_wa_validator_example`.
- `commercial_claims_allowed=false`.
- Nodes comerciais ausentes:
  - zero `brand`;
  - zero `product_group`;
  - zero `product`;
  - zero `copy`;
  - zero `offer`.
- Existem 12 FAQs, mas são seis saudações e seis perguntas de qualificação.
- FAQs comerciais elegíveis: zero.
- Claims comerciais aprovados: zero.
- O Embedded não contém catálogo comercial recuperável.
- `/api/menu/tock-fatal` possui uma collection sem produtos.

Os produtos não estão apenas desconectados: também estão ausentes da fonte canônica
`knowledge_nodes` em produção.

### 4.2 Evidência de conversa

No lead técnico 33, variações de “quais produtos tem?” — inclusive o áudio
preservado como `[audio do cliente]: E quais produtos tu tem aí?` — produziram
respostas como:

- “Que legal!”;
- “Entendi, você quer saber o que temos.”;
- “Entendi, você quer saber o que temos/produtos temos.”

Os proofs examinados eram tecnicamente válidos e exactly-once, mas falharam em
qualidade: `faq_candidates=[]`, `selected_faq=null` e evidências comerciais vazias.

Depois de handoff/ausência de jornada, `no_journey_policy_v4` conserva apenas as
declarações da proposta do modelo. Como não existe conteúdo de catálogo, a pergunta
gerada é removida e sobra somente uma confirmação social vazia. Esse comportamento
explica a percepção de que a persona está “muito burra”.

### 4.3 Defeito de seleção de público

O campo `purchase_profile` tem aliases, mas foi publicado com:

- `normalization=null`;
- `overwrite_policy=never`.

Duas respostas literais “uso próprio” não foram extraídas corretamente; a segunda
virou `unknown(reason=ignored_twice)` e uma confirmação posterior levou ao branch de
revenda. A primeira correção deve ser declarativa:

- adicionar `normalization_hint`:
  - `uso próprio`, `pra mim` -> `uso-proprio-varejo`;
  - `revenda`, `atacado`, `minha loja` -> `atacado-revenda`;
- usar `overwrite_policy=explicit_correction`;
- preservar estados `known` e `needs_confirmation`.

Se isso ainda falhar no WA Validator, abrir então um defeito genérico de extração de
enum no runtime, sem hardcode para Tock.

### 4.4 Fonte comercial e conflito de draft

O site público `https://tockfatal.com/` apresenta atualmente:

- Coleção Modais de Inverno;
- Kit Modal 1 — 9 cores disponíveis;
- Kit Modal 2 — Urso Estampado;
- preço exibido de R$ 59,90 para cada item na captura auditada;
- posicionamento de atacado/revenda e pronta entrega.

Existe um intake local não promovido em
`.runtime/kb-intake-sessions/ffddb22e-4bca-496d-8c51-36507036d420.json` que
registra `price.unit.amount=249.00` e fonte genérica `shopify_json`. Esse draft
conflita com o site observado e não deve ser reutilizado ou publicado cegamente.

As fontes locais de apoio são:

- `docs/tock-fatal-modal-marketing-graph.md`;
- `docs/e2e-tock-fatal-catalog-graph.md`.

Elas servem como candidatos para reconstrução, não como autorização para publicar
preço, estoque ou política desatualizados.

## 5. PublicationPlan proposto para a Tock Fatal

Construir a próxima revisão pelo pipeline GraphBundle genérico com o caminho:

`Persona -> Brand -> Campaign -> Audience -> ProductGroup -> Product -> Copy -> FAQ -> Embedded`

Nodes mínimos:

- Brand: Tock Fatal;
- Campaign: Coleção Modais de Inverno;
- Audiences: atacado/revenda e uso próprio/varejo;
- ProductGroup: Modais de Inverno;
- Product: Kit Modal 1;
- Product: Kit Modal 2 — Urso Estampado;
- copies de catálogo e copies específicas por produto/audiência;
- nove FAQs iniciais.

FAQs propostas, todas inicialmente `pending_validation`:

1. `faq-catalogo-modais` — “O que a Tock Fatal vende?”
2. `faq-produtos-catalogo` — “Quais produtos estão no catálogo?”
3. `faq-kit-modal-1-descricao` — “O que é o Kit Modal 1?”
4. `faq-kit-modal-1-preco` — “Quanto custa o Kit Modal 1?”
5. `faq-kit-modal-2-descricao` — “O que é o Kit Modal 2?”
6. `faq-kit-modal-2-preco` — “Quanto custa o Kit Modal 2?”
7. `faq-modais-conforto` — “Como são os modais?”
8. `faq-pronta-entrega` — “Tem pronta entrega?”
9. `faq-modais-revenda` — “Esses modais são indicados para revenda?”

Cada FAQ deve conter `source`, `source_url`, `captured_at`, fingerprint/trecho de
evidência, `source_node_id`, `source_node_type`, `branch_path`, claim type e
exatamente um pai estrutural primário. A edge para Embedded só entra depois da
aprovação.

Não publicar sem nova fonte ou confirmação do operador:

- nomes individuais das nove cores;
- tamanhos;
- composição exata dos kits;
- pedido mínimo;
- frete e prazo;
- troca/devolução;
- estoque por variante;
- aceitação formal de varejo/uso próprio;
- famílias tricô e cropped marcadas como `pending_source`.

## 6. Aurora — estado atual e causa do handoff ausente

### 6.1 Publicação ativa

- Graph publication: v67.
- Checksum observado: `sha256:bb40f955...`.
- Compilador: `graph-compiler-v3.6.2`.
- Aproximadamente 15 produtos, 44 FAQs e 35 FAQs elegíveis.
- As quatro FAQs de reabertura, múltiplos serviços, troca e remoção já estão
  aprovadas, ligadas à regra de atendimento e projetadas no RAG.

Logo, não falta projeção das FAQs já publicadas e o problema não se resolve apenas
republicando essas mesmas quatro entradas.

### 6.2 Evidência do handoff pós-conversão

No lead técnico 34, a segunda jornada foi convertida como compra concluída e depois
fechada como entregue. Em seguida, o cliente enviou:

`[audio do cliente]: Eu quero uma lavagem. Lavagem.`

O estado observado foi:

- decisão: `route=HUMAN`;
- motivo: `post_sale_operation`;
- proof: válido, com `handoff_required=true`;
- resultado persistido: `handoff=false` e `ai_paused=false`;
- outbound automático: “Perfeito, Allan! Lavagem detalhada então.”

O runtime reconheceu corretamente uma operação humana após conversão, mas não
comunicou nem efetivou o handoff.

### 6.3 Causa confirmada no runtime

- `_no_journey_route()` retorna `HUMAN` para operação pós-venda.
- `_without_journey_mutation()` força `handoff_required=False`.
- `_no_journey_reply()` prefere declarações livres do modelo antes do fallback do
  grafo.
- A política publicada contém `post_sale_operation_route: HUMAN`, mas não possui
  uma mensagem obrigatória de handoff pós-venda.

Isso cria a contradição `route=HUMAN` sem handoff real. Uma FAQ consegue influenciar
texto informativo, mas não consegue inverter o `handoff=false` imposto pelo runtime.

Há ainda uma hipótese separada a validar para novas jornadas: a supressão de
`terminal_repetition` pode considerar o mesmo terminal intent duplicado entre
jornadas diferentes. Se reproduzida, a deduplicação deverá ser escopada por
`journey_id/journey_sequence`, continuando proibida dentro da mesma jornada.

### 6.4 Comportamento robótico observado

- “tudo bem?” recebeu nova apresentação da Lia, sem responder à pergunta social;
- “sim” produziu apenas “Entendi, Allan!”;
- “ok” repetiu uma informação já enviada;
- catálogo apareceu como lista longa numa única frase;
- pedidos pós-venda receberam confirmação curta sem explicar o encaminhamento;
- saudações, confirmações e resumos têm poucas variações executáveis.

As execuções n8n correspondentes terminaram com sucesso; são falhas semânticas, não
prova de falha de transporte.

## 7. PublicationPlan proposto para a Aurora

Manter o workflow atual. Não ressincronizar n8n se a mudança for somente de grafo.

Adicionar sob a regra operacional, com fonte e branch path, FAQs inicialmente
`pending_validation` sobre:

1. adicionar ou trocar serviço depois de agendamento confirmado;
2. quem confirma alterações depois do agendamento;
3. o que acontece após confirmar os dados do pedido;
4. novo pedido depois de atendimento concluído;
5. dúvida meramente informativa depois do agendamento.

Adicionar ao `conversation_policy`/tone, não como FAQ dinâmica:

- copy publicada para handoff pós-agendamento;
- resposta social breve antes de retomar o fluxo;
- proibição de resposta composta apenas por “Entendi”, “Perfeito” ou “Ótimo”;
- uma frase de reconhecimento e uma ação clara por turno;
- catálogo agrupado por objetivo;
- variações de transição, confirmação e resumo;
- não reapresentar a Lia em turnos consecutivos;
- evitar repetir fatos e perguntas ainda válidos.

Essas mudanças melhoram o texto, mas não garantem handoff real enquanto o runtime
continuar zerando `handoff_required`.

## 8. Única correção de backend recomendada

Aplicar uma correção pequena, genérica e orientada pelo grafo:

1. Se a política final resolver `route=HUMAN`, preservar o
   `handoff_required` aplicável em vez de zerá-lo em
   `_without_journey_mutation()`.
2. Usar uma mensagem publicada no grafo, por exemplo
   `post_sale_operation_handoff_message`, para compor o outbound.
3. Garantir `handoff=true` e pausa da IA conforme a política/binding.
4. Não inserir copy, nome de persona, marca ou serviço no backend.
5. Se a hipótese de repetição terminal entre jornadas for reproduzida, escopar a
   deduplicação por jornada.

Essa mudança preserva a separação arquitetural: conteúdo no GraphBundle, decisão
genérica no runtime e transporte no n8n.

## 9. Risco de release

Foi observado skew entre os releases de produção:

- API: `09b6c9c7618c6bf31caa86f9a43758ae72af52ec`;
- workers: `c5936b648327ba0e65a71c71b3013a000beb4e7e`.

Isso não explica diretamente o caso de resposta via API/n8n, mas é risco para filas,
reativação, pause/resume e deploy. API e workers devem estar no mesmo SHA antes da
retomada após um futuro deploy.

## 10. Sequência de execução recomendada

1. Auditar novamente SHA, health/readiness e o estado do binding da persona
   alvo. Não pausar bindings de personas não envolvidas em publicação isolada
   de conteúdo.
2. Gerar o GraphBundle candidato da Tock a partir das fontes atuais.
3. Gerar PublicationPlan com diff, checksums, custo e validation errors.
4. Obter aprovação humana de produtos, claims, preços e FAQs.
5. Publicar/ativar a Tock primeiro, conforme o roadmap.
6. Fazer dry-run de resync do workflow Tock e aplicar apenas se o drift semântico
   persistir.
7. Validar a Tock pelo WA Validator direto.
8. Implementar e revisar a pequena correção genérica de handoff.
9. Gerar/aprovar/publicar tone, policy e FAQs operacionais da Aurora.
10. Validar a Aurora pelo WA Validator direto.
11. Fazer deploy com API e workers no mesmo SHA.
12. Só retomar os bindings/workers efetivamente pausados pela operação mediante
    autorização explícita posterior.

Não combinar aprovação de conteúdo, publicação, resync, deploy, limpeza e retomada;
cada mutação exige seu próprio gate conforme `AGENTS.md`.

## 11. Critérios de aceite

### Tock Fatal

- “o que vende?”, “quais produtos?”, “tem modal?”, “qual valor?” e “tem pronta
  entrega?” selecionam FAQ/evidência do branch correto;
- nenhuma resposta vazia como “Que legal!” ou reconhecimento sem ação;
- “uso próprio” e “pra mim” selecionam varejo na primeira resposta;
- “revenda”, “atacado” e “minha loja” selecionam revenda;
- áudio permanece integralmente prefixado com `[audio do cliente]:`;
- dúvida informativa após handoff responde FAQ sem abrir jornada;
- conteúdo publicado aparece no grafo, KB filtrada por persona e RAG.

### Aurora

- após `appointment_booked`, pedido de alteração retorna `route=HUMAN`, aviso
  explícito, `handoff=true` e IA pausada, sem alterar automaticamente o agendamento;
- após handoff sem conversão, novo serviço abre jornada e reaproveita dados válidos;
- “oi” seguido de “tudo bem?” responde socialmente sem reapresentação repetida;
- “sim” e “ok” avançam, confirmam ou explicam o estado;
- nenhuma pergunta/fato válido é repetido;
- FAQ selecionada aparece nas evidências do proof.

### Invariantes técnicos

- exatamente um inbound canônico;
- exatamente uma decisão;
- exatamente um proof válido;
- exatamente um commit;
- no máximo um outbound inerte;
- nenhum WhatsApp real;
- zero replay, CAS conflict ou outbound duplicado;
- publicação ativa com checksum aprovado;
- API e workers no mesmo SHA antes da retomada.

## 12. Próximo gate

Nenhuma mutação está autorizada por este handoff. A próxima sessão deve solicitar e
registrar aprovação do PublicationPlan antes de materializar/publicar conteúdo. O
ajuste de backend, resync n8n, deploy e retomada operacional continuam sendo gates
separados.

