# Mapa de transicao para VPS

## Estado atual

- Dashboard: projeto Vercel `brain-plataform`, root `dashboard`.
- Backend e banco: stack self-hosted prevista em `docker-compose.yml`.
- Dominios definidos: `api.vzforeal.com` e `n8n.vzforeal.com`.
- VPS informada: `179.197.233.12`.
- n8n: ainda nao faz parte do Compose principal e deve permanecer isolado na primeira fase.
- SSH: host responde, mas a chave autorizada ainda nao esta disponivel nesta maquina.

## Fases

### Fase 0 — release controlada

1. Preservar as alteracoes locais atuais.
2. Executar testes Python, build do dashboard e validacao do Compose.
3. Revisar e commitar somente o release aprovado.
4. Promover o release para `main`.
5. Confirmar o deploy Vercel do projeto `brain-plataform`.

### Fase 1 — backend e banco na VPS

1. Instalar Docker, Compose, firewall e acesso SSH por chave.
2. Criar `/opt/brain-ai` e transferir manifests.
3. Criar `.env.compose` somente na VPS.
4. Configurar DNS A para `api.vzforeal.com` e `storage.vzforeal.com`.
5. Subir Postgres, migrations, API, workers, Storage, Kong e Caddy.
6. Fazer backup/restore de ensaio antes de migrar dados definitivos.
7. Validar `/health/ready`, login, isolamento por persona, menu publico, assets e grafo.

### Fase 2 — n8n isolado

1. Criar um segundo projeto Compose, com volume proprio e credenciais proprias.
2. Nao compartilhar a rede Docker, banco, volumes ou secrets do Brain.
3. Publicar apenas `n8n.vzforeal.com` com TLS.
4. Manter workflows inativos e sem credenciais Meta na primeira subida.
5. Validar login administrativo e persistencia do n8n.
6. Registrar os workflows existentes, IDs, webhooks e credenciais necessarias.

### Fase 3 — transicao de integracao

1. Escolher n8n como receptor primario do webhook Meta ou definir receptor direto no Brain.
2. Criar token separado para `POST /process`.
3. Mapear persona, lead, telefone, `message_id` e `whatsapp_phone_number_id`.
4. Testar inbound sem resposta destrutiva.
5. Testar outbound com assinatura HMAC e idempotencia.
6. Ativar uma persona piloto e observar logs, duplicacoes e falhas.

## Bloqueios atuais

- Falta chave SSH autorizada para `root@179.197.233.12`.
- Falta confirmar se a VPS ja possui dados/containers que nao podem ser alterados.
- Falta acesso DNS para criar os registros.
- Falta decidir se `storage.vzforeal.com` sera o subdominio publico de Storage.
- Falta definir e-mail para certificados ACME.
- Falta confirmar o diretorio de aplicacao na VPS.
- Falta export dos workflows e credenciais do n8n atual, se existir.

## Regra de seguranca

Nao enviar senha, chave privada, token Meta, token n8n ou chave de provedor no repositorio ou na conversa. Segredos entram apenas em `.env.compose` na VPS, secrets do GitHub ou credenciais internas do n8n.
