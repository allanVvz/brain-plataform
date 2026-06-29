# Claude Project Contract

Use this file as a root orientation layer. The source of truth remains
`PROJECT_REQUIREMENTS.md`.

## Core Rules

- Graph JSON v2 is the canonical published graph contract for the Graph UI.
- Persona access must be validated on every persona-scoped read and mutation.
- User API keys are stored encrypted server-side and must never be sent to the
  browser.
- Public site output is configured in `personas.config.public_site` and rendered
  from the persona memory/graph through `/api/menu/{persona_slug}`.
- Public site formats are fixed by `public_site_formats`; initial keys are
  `cardapio`, `landing_page` and `catalogo_roupas`.
- Public WhatsApp CTA uses `whatsapp_phone` and `whatsapp_message_template`.
  Do not use or expose Meta/n8n `whatsapp_phone_number_id` for this link.

## Required Reading Before Larger Changes

- `PROJECT_REQUIREMENTS.md`
- `memory.md`
- `AGENTS.md`
- `docs/knowledge-flow.md`
