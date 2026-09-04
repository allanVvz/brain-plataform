# Roadmap — WhatsApp Business App + Cloud API (Coexistência)

## Objetivo

Permitir que uma persona use o mesmo número no aplicativo WhatsApp Business e
na API oficial Meta, mantendo o Brain como consumidor da API. O produto deve
mostrar claramente quando a coexistência está disponível, em onboarding,
operacional, degradada ou desligada.

O objetivo não é trocar o provedor de uma persona automaticamente nem
desregistrar números existentes. Essas ações permanecem operações explícitas,
auditáveis e com pausa apenas da persona afetada.

## Estado atual

O dashboard já possui o padrão que será reutilizado:

| Área | Rota atual | Papel atual |
| --- | --- | --- |
| Administração | `/configuracoes?sub=canal` | Seleciona Meta Cloud/Evolution e configura o binding Meta ou o provisionamento Evolution. |
| Portal do cliente | `/clientes/{persona}/configuracoes` | Exibe estado do canal e permite apenas concluir o QR temporário de Evolution. |

O código atual não contém Embedded Signup nem suporte a coexistência. O
provider `meta_cloud` recebe manualmente `whatsapp_phone_number_id`; isto não
é suficiente para criar a relação entre o aplicativo WhatsApp Business e a
Cloud API.

## Princípios de produto e segurança

- Coexistência é uma capacidade do canal `meta_cloud`, não um novo provider e
  não uma sessão Evolution.
- Não criar tabela nova. O estado operacional fica em `whatsapp_channel_bindings.metadata`; credenciais e códigos de curta duração ficam somente no secret store/estado efêmero do servidor.
- Nunca mostrar token, app secret, `phone_number_id`, QR em texto ou dados de
  cadastro Meta ao cliente. IDs técnicos são mascarados na UI.
- O cliente jamais pode desregistrar, migrar, substituir binding ou escolher
  WABA. Essas operações são exclusivas de administrador com motivo registrado.
- Uma ação de alto impacto exige preview, confirmação digitada e auditoria em
  `system_events`; não há botão único de "converter".
- Pausa, desregistro, retomada e qualquer teste de conversa são autorizações
  separadas. O produto nunca pausa outros bindings/personas.

## Experiência proposta

### 1. Administração — Mensageria > Canal

Manter o seletor atual `Meta Cloud | Evolution`. Ao selecionar Meta Cloud,
incluir um cartão **WhatsApp Business App** abaixo da configuração Meta.

Estados visíveis:

```text
Cloud API somente
  → elegibilidade pendente
  → pronto para iniciar coexistência
  → aguardando confirmação no app
  → sincronizando
  → coexistência ativa
  → atenção: app inativo / webhook sem eco / binding pausado
  → desligado
```

Ações do administrador:

1. **Verificar elegibilidade** — somente leitura; consulta configuração Meta,
   binding e requisitos do parceiro.
2. **Preparar onboarding** — salva uma sessão efêmera, cria o link/QR de
   Embedded Signup e ainda não troca binding.
3. **Acompanhar confirmação** — apresenta progresso e logs sanitizados.
4. **Aplicar binding após confirmação** — preview do binding técnico e do
   webhook; requer confirmação explícita.
5. **Pausar ou retomar esta persona** — operação separada já existente, com
   motivo e estado claramente exibidos.
6. **Desligar coexistência** — somente após explicar a consequência e com
   auditoria; nunca implica apagar WABA ou histórico.

O admin vê também o fornecedor que iniciou o Embedded Signup, WABA mascarada,
número mascarado, data da última atividade do app, integridade de webhooks e
versão do contrato de transporte.

### 2. Cliente — Configurações > Canal WhatsApp

Reutilizar o cartão de canal atual. Para um canal Meta elegível, expor somente
um fluxo guiado, sem credenciais:

1. card "Conectar WhatsApp Business" com pré-requisitos: app instalado,
   número acessível e app atualizado;
2. botão **Abrir conexão segura**;
3. QR/link temporário emitido pelo servidor;
4. instrução para confirmar/ler no WhatsApp Business;
5. polling de estado e confirmação final "Conectado ao atendimento".

O portal não oferece a opção se o número estiver somente em Cloud API e o
parceiro não confirmar conversão compatível. Nesse cenário mostra:
"Este número precisa de migração assistida pelo administrador; nenhuma ação
foi executada."

## Contrato de integração

Criar um adaptador de onboarding Meta/Embedded Signup no control-plane; o
transport continua sendo o único responsável por inbound/outbound. O runtime
de conversa não recebe credenciais Meta nem detalhes de onboarding.

Contratos propostos, todos autenticados e com controle por persona:

| Endpoint | Papel |
| --- | --- |
| `GET /portal/personas/{slug}/channels/whatsapp/coexistence` | Estado sanitizado para admin/cliente. |
| `POST /portal/personas/{slug}/channels/whatsapp/coexistence/eligibility-check` | Dry-run administrativo. |
| `POST /portal/personas/{slug}/channels/whatsapp/coexistence/onboarding-session` | Cria sessão temporária e devolve QR/link de curta duração. |
| `GET /portal/personas/{slug}/channels/whatsapp/coexistence/onboarding-session/{id}` | Progresso, sem segredos. |
| `POST /portal/personas/{slug}/channels/whatsapp/coexistence/apply-binding` | Aplica somente após `FINISH` confirmado e preview aprovado. |
| `POST /portal/personas/{slug}/channels/whatsapp/coexistence/disconnect` | Ação administrativa destrutiva, com motivo. |

O adaptador deve suportar inicialmente um único parceiro escolhido pela
empresa, mas manter interface para mais de um. Não acoplar código de runtime a
nome de parceiro, WABA, persona ou telefone.

Campos previstos em `metadata.coexistence` do binding existente:

```json
{
  "state": "api_only | eligibility_pending | onboarding | active | degraded | disconnected",
  "onboarding_provider": "<identificador generico>",
  "onboarded_at": "timestamp",
  "last_app_activity_at": "timestamp",
  "last_echo_at": "timestamp",
  "sync_state": "not_requested | running | complete | failed",
  "contract_version": 1
}
```

Tokens, códigos e QR não entram nesse JSON nem em logs.

## Fases de entrega

### Fase 0 — decisão e descoberta

- Escolher o parceiro Meta/BSP ou decidir implementar Embedded Signup com uma
  aplicação Meta aprovada.
- Confirmar por escrito se ele aceita a rota Cloud API → App → coexistência
  para números existentes, no Brasil, e quais são os requisitos/custos.
- Levantar persona, binding, WABA e número somente de forma mascarada.
- Produzir matriz de elegibilidade por número. Sem mudança produtiva.

**Saída:** parceiro escolhido e um número elegível confirmado.

### Fase 1 — contrato e estado administrativo

- Definir adaptador, estados e eventos auditáveis.
- Adicionar as rotas read-only, o modelo sanitizado e o cartão Admin.
- Mostrar `api_only` para bindings atuais sem mudar seu comportamento.
- Cobrir autorização admin/persona, mascaramento e ausência de segredos.

**Saída:** operador enxerga o diagnóstico e nenhum número é modificado.

### Fase 2 — onboarding controlado

- Implementar criação/expiração de sessão segura e retorno do fluxo do
  parceiro/Meta.
- Adicionar o cartão simplificado no portal cliente.
- Registrar transições, falhas e callbacks idempotentemente.
- Não aplicar binding, assinar webhooks ou retomar agentes de forma automática.

**Saída:** o usuário consegue concluir o pareamento no app e o sistema apenas
registra a confirmação.

### Fase 3 — ativação técnica

- Implementar preview e aplicação explícita do binding pós-confirmação.
- Configurar webhook e campos necessários ao transporte sem expor segredos.
- Processar `smb_message_echoes`/eventos de sincronização separadamente do
  inbound canônico para não duplicar decisão ou outbound.
- Exibir estado degradado se o app ficar inativo ou o eco interromper.

**Saída:** coexistência ativa, binding consistente e observável.

### Fase 4 — operação segura

- Criar playbook de pausa de uma persona, conversão assistida, rollback e
  desligamento.
- Alertar sobre app inativo, webhook inválido, sync incompleto e divergência
  de binding.
- Criar painel de auditoria por sessão com IDs técnicos, timestamps e motivos.

**Saída:** suporte operacional sem depender de acesso manual ao banco.

### Fase 5 — liberação controlada

- Auditoria produtiva read-only e dry-run do número piloto.
- Pausar apenas o binding/pessoa piloto no momento autorizado.
- Executar onboarding e conferir provas, ledger, idempotência e integridade de
  webhook por sessões sintéticas internas.
- Retomar somente por autorização posterior. WA Validator e WhatsApp real
  ficam fora deste roadmap até autorização específica.

**Saída:** piloto documentado antes de habilitar outras personas.

## Critérios de aceite

- Admin vê o estado e inicia somente sessões autorizadas da persona correta.
- Cliente vê apenas o seu próprio canal e nunca credenciais/IDs sensíveis.
- Falha, expiração ou cancelamento não altera binding existente.
- Cada inbound canônico continua gerando no máximo uma decisão e um outbound;
  eco do app não cria duplicidade.
- Não há pausa global para onboarding isolado; a retomada é manual e auditada.
- Toda alteração tem `request_id`, ator, motivo, binding mascarado e timestamp.

## Decisões pendentes

1. Qual parceiro Meta/BSP será usado para o Embedded Signup de coexistência.
2. Se a empresa aceita uma rota de conversão com indisponibilidade temporária
   caso o número atual não seja elegível para conexão direta.
3. Qual persona/número será o piloto, após a fase de elegibilidade.

