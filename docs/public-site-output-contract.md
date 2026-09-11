# Public Site Output Contract

This document defines the current public-site contract for landing pages,
cardapios and catalogs.

## Current Flow

```text
persona memory and graph
-> /api/menu/{persona_slug}
-> external public-site renderer
```

The endpoint keeps the existing `persona.collections[]` shape and adds a
top-level `site` object.

## Site Config

Per persona config lives in `personas.config.public_site`:

- `site_slug`: public slug, unique across personas.
- `site_name`: display name for the generated site.
- `format_key`: active output format key.
- `default_collection_slug`: collection consumed by the current payload.
- `whatsapp_phone`: public WhatsApp CTA phone, digits only after normalization.
- `whatsapp_message_template`: text encoded into the `wa.me` link.

The externally published URL remains `personas.catalog_url`.

## Shared Card-pio deployment (corrected 2026-09-11)

> The section below describing `baita-cardapio.vercel.app` and a per-persona
> `VITE_AI_BRAIN_API_URL`/`ALLOWED_ORIGINS` pair is **obsolete and describes a
> broken deployment**: `baita-cardapio.vercel.app` proxies to a hostname that
> no longer resolves (`DNS_HOSTNAME_NOT_FOUND`), confirmed 2026-09-11.

The actual `Card-pio` repository ships **one Vercel project** aliased to
multiple domains (`tockfatal.com`, `lp-catalogo-cardapio.vercel.app`, etc.).
Its `vercel.json` has a single project-wide rule, `/api-brain/(.*) ->
https://lpapi.vzforeal.com/$1`, and a generic SPA route for `/cardapio/:slug`.
This means **any** persona's cardapio works automatically, with zero
per-persona domain, env var, or CORS setup, at:

```
https://lp-catalogo-cardapio.vercel.app/cardapio/{site_slug}
```

`personas.catalog_url` is optional. `public_site_payload` (in
`services/public_site.py`) derives this exact URL automatically from
`site_slug` + the format's `default_route_prefix` whenever `catalog_url` is
unset — set `catalog_url` explicitly only for a persona with a real branded
domain (e.g. Tock Fatal's `tockfatal.com`), never to point at the shared
Card-pio domain by hand.

`baita-conveniencia`'s `site_slug` is `baita` (default collection
`cardapio-baita-v14`); `vz-lupas`'s `site_slug` is `vz-lupas`.

## Format Registry

Formats are stored in `public_site_formats`; the dashboard only selects active
rows. Initial keys:

- `cardapio`
- `landing_page`
- `catalogo_roupas`

New formats must be added by DB/migration for now.

## Public Payload

`GET /api/menu/{persona_slug}` must expose:

- `site.slug`
- `site.name`
- `site.format_key`
- `site.format_label`
- `site.route_path`
- `site.catalog_url`
- `site.default_collection_slug`
- `site.whatsapp.phone`
- `site.whatsapp.message_template`
- `site.whatsapp.href`

Do not expose Meta tokens, n8n secrets, user API keys or
`whatsapp_phone_number_id` in this payload.

## Branch block payload

The generated branch-scoped landing payload additionally exposes:

- `site.visual_identity.logo.primary|round|reverse`
- `site.visual_identity.palette` with channel-specific semantic colors
- `site.visual_identity.typography.display|body`
- `site.visual_identity.css_variables`

The same `visual_identity` object is repeated in the `hero` and `brand`
blocks. This lets renderers apply the logo, palette and real brand font from
the first paint while keeping every visual decision sourced by the selected
branch in the graph. Tock Fatal uses distinct palettes for `varejo` and
`atacado`; renderers must not merge or fall back across those branches.
