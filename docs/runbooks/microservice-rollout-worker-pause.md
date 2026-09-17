# Rollout de microsserviços e pausa de workers

## Release compatível

Uma alteração compatível usa `Integrated microservice release` e inclui apenas
os serviços alterados. Não usa pausa global, `prepare` ou `finish`.

O workflow executa, por serviço:

1. preflight read-only;
2. API candidata no slot inativo, sem consumidores de fila;
3. health/readiness e confirmação do SHA;
4. drain dos consumidores antigos por até 45 segundos;
5. início dos consumidores do novo slot;
6. cutover somente das rotas daquele serviço;
7. canário interno; para conversation-runtime, WA Validator sem WhatsApp real;
8. rollback automático de rota, API e workers se o canário falhar.

Exemplo runtime-only:

```bash
gh workflow run "Integrated microservice release" \
  --ref main \
  -f manifest_sha=<sha-do-manifesto> \
  -f action=deploy \
  -f services=conversation-runtime \
  -f canary_persona_slug=<persona-de-validacao> \
  -f canary_flow_id=<fluxo-wa-interno>
```

Gateway, control-plane e transport conservam seus SHAs, digests, slots e
containers. Disparos repetidos para o mesmo serviço/SHA reutilizam a imagem e
não repetem a promoção.

## Manifesto incremental

Cada entrada em `services` possui proveniência própria. Para atualizar um
serviço, renderize a partir do manifesto anterior e forneça somente o novo
digest; as outras entradas permanecem inalteradas.

```bash
python ops/microservices/render-monorepo-release-manifest.py \
  --base-manifest ops/microservices/release-manifest.json \
  --source-sha <sha-do-runtime> \
  --conversation-runtime-digest <sha256:digest> \
  --output <manifesto-candidato.json>
```

## Quando a pausa global ainda é permitida

Somente releases classificados como `migration` ou
`breaking_queue_contract` usam o fluxo coordenado:

1. autorização explícita da pausa;
2. `rollout-microservices.sh prepare`;
3. release coordenado;
4. `rollout-microservices.sh finish`;
5. `rollout-microservices.sh status`.

`claims-paused.json` é global e não deve ser usado para uma mudança compatível.
Se uma operação compatível exigir reiniciar serviço não afetado, sincronizar
código manualmente na VPS ou executar comandos corretivos, interrompa o rollout
e corrija o pipeline.
