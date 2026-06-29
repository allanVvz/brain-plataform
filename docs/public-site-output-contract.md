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
