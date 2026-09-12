# GraphBundle v3 Readiness — `vz-lupas` and `baita-conveniencia`

Date: 2026-09-12
Scope: read-only. No production access — the production node/edge/publication
counts below were supplied by the task orchestrator and are treated as given
facts, not re-verified here. The v3 requirements themselves were read directly
from `apps/control-plane/api/routes/menu.py` (the only source of truth for
what the publication endpoint actually enforces).

## 1. How to read this document

`GET /api/menu/{persona_slug}` has two paths:

- **v3 path** — an active row in `graph_publication` for the persona. Its
  `document_json` is read as an immutable, already-compiled artifact and
  projected straight into the public payload.
- **legacy path** — no active publication row. The endpoint falls back to
  reading `graph_json_v2` / raw knowledge rows directly.

`tock-fatal` is the only persona today with an active `graph_publication`
(v33), so it is the only persona on the v3 path. `vz-lupas` and
`baita-conveniencia` have **no active `graph_publication` row at all**, which
is why they still render (via the legacy path) despite having hundreds of
nodes.

**Fail-closed rule, read from `_active_publication_context` (menu.py:50-131):
once a `graph_publication` row exists and is active, any structural defect in
it raises `HTTP 503` and does NOT fall back to legacy.** There is no partial
credit and no silent degrade. This matters operationally for both personas:
the first attempt to activate a v3 bundle for either of them must be correct,
or the public site goes from "working legacy site" to "503" the moment the
bad publication is marked active.

## 2. The v3 requirements checklist (derived from code)

### 2a. Publication identity (`_active_publication_context`, menu.py:50-131)

Only evaluated once a `graph_publication` row is active for the persona.

- [ ] `publication.persona_id == persona_id`
- [ ] `document.persona.id == persona_id`
- [ ] `document.persona.slug == persona_slug`
- [ ] `document.schema_version == "3.0"`
- [ ] `publication.id` is present
- [ ] `publication.version` is an integer
- [ ] `checksum` (publication or document) starts with `sha256:`
- [ ] if both `publication.checksum` and `document.checksum` are present, they match
- [ ] at least one `gallery`-type node exists in the document, and the nodes
      meant to be public each carry a `publishes_to` edge into it — this is
      the **only** grant mechanism; a node with no `publishes_to` edge to a
      gallery is invisible to every downstream check, whatever its content.

### 2b. `persona.data.public_site` contract (`_canonical_site_from_publication`, menu.py:876-1171)

All errors accumulate and are reported together as one `HTTP 503
public_site_contract_incomplete` — there is no partial site.

- [ ] Exactly 1 `persona` node in the **granted** node set
- [ ] `persona.data.public_site` is an object
- [ ] Required non-empty strings on it: `slug`, `name`, `format_key`,
      `default_collection_slug`, `brand_family`, `brand_channel`
- [ ] `whatsapp.phone` normalizes to ≥8 digits
- [ ] `whatsapp.message_template` is required natural-language text (no bare
      technical node-id tokens — `_TECHNICAL_ID_PATTERN` bans leaking
      `product:`, `grupo:`, `asset:`, etc. into customer-facing copy)
- [ ] Identity kit — **all three required, no partial credit**:
      `identity.logo_round`, `identity.logo_wordmark`, `identity.logo_reverse`,
      each resolving through `_site_asset` to a granted, approved,
      registry-backed, stable-HTTPS asset. (`logo_short` is explicitly
      optional — the code comments call it "a rollout-in-progress
      enhancement" that must never 503 a persona that hasn't authored one.)
- [ ] `pages[]` — **≥ 2 entries**. Each page references a `campaign` node,
      needs a `route` starting with `/`, `kind` in `{linktree, showcase}`,
      required `title` + `description`, and each `action` needs a valid
      `kind` (`internal|whatsapp|location|disabled`), `id`, `label`, and (if
      pointing at a node) a resolvable `node_id`. Any `kind == "showcase"`
      page additionally requires a full `sections` block: `audiences
      {eyebrow, title}`, `groups {eyebrow, title, item_eyebrow,
      item_description}`, `final_cta {title, description, action_label}`.
- [ ] `contacts[]` — **≥ 1 entry**, each referencing a `copy` node with `key`,
      `label`, a valid phone (≥8 digits), and a message template.
- [ ] `covers[]` — **≥ 1 entry**, each a granted/approved asset, `position`
      0-2, and `focal_point.desktop == "full"` /
      `focal_point.mobile == "split-halves"` **exactly** (no other values
      accepted).
- [ ] `audiences[]` — **≥ 1 entry**, each referencing an `audience` node with
      `label` + `message_template`.
- [ ] `locations[]` — **≥ 1 entry**, each referencing a `campaign` node whose
      `campaign_subtype == "physical_store"`, with `label`, `address`, valid
      `coordinates` (lat/lon in range), a public HTTPS `google_maps_url`, and
      (if present) a valid `google_business_url`/map `style_url`/hex
      `marker_color`.

### 2c. Catalog / grant contract (`_compiled_catalog_payload`, menu.py:577-874)

- [ ] Exactly 1 `brand` node in the granted set
- [ ] Every `product`, `product_group`, `copy`, `faq` node that should be
      public must carry its own `publishes_to → gallery` edge — being
      *reachable* from a granted parent is not enough, each node type is
      filtered by `node_id in granted_node_ids` independently
- [ ] Every product must be linked to a `product_group` via one of
      `product_group_has_product | in_category | category_has_product |
      contains` — an unlinked product raises
      `{product_id}:published_group_relation_required`
- [ ] Every category (product_group) needs a resolvable CTA
      (`{id}:cta_required` otherwise)
- [ ] Any product that has at least one asset must also have a CTA
- [ ] Assets (product images, brand logo/cover, group covers, campaign
      banners) resolve only through a **two-registry chain**: the graph
      `asset` node must (a) be granted via `publishes_to→gallery` and carry a
      `registry_id`/`asset_id`, AND (b) that id must match a row in the
      `assets` platform table for the **same persona_id**, with
      `approval_status == "approved"` and `status` not in
      `{archived, rejected, failed}`, AND (c) that row's storage `bucket` +
      `path` must resolve to a stable `https://.../storage/v1/object/public/…`
      URL with no query/fragment. Any break in that chain drops the asset
      silently from `_compiled_asset_payload` and, for the identity/cover
      slots, becomes a hard `public_site_contract_incomplete` error.
- [ ] `offer` nodes are optional — price falls back to the product node's own
      `data`/`metadata` via `normalize_offer` if no `about_product` offer
      edge exists.

### 2d. Correction (2026-09-12, same day): assets are not a single Product-level chain

An earlier reading of this report (and of
`docs/VZ_LUPAS_GRAPH_REBUILD_DEFINITION_OF_DONE.md`, corrected in the same
pass) treated "assets" as one undifferentiated gap, implicitly modeled as
`Product -> Asset -> Gallery`. That is wrong. `_compiled_catalog_payload`
(menu.py:577-874) reads four distinct owner→asset relations —
`brand_has_asset` (identity kit + brand cover), `campaign_has_asset`
(hero/footer banners), `category_has_asset` (Product Group cover), and
`uses_asset` (Product image) — and a Product Group with no cover of its own
falls back to the first Product asset found beneath it (menu.py:780-781).
Separately, `resolve_catalog_media` (`brain_contracts/catalog_media.py`,
used for WhatsApp media sends, not the public site) resolves Product/Group
media with inheritance in both directions between a group and its products.

This matters for the gap read below: the identity kit (§2b) is 3
Brand-level images, not one per Product; `covers[]` and category covers are
Brand/Campaign/Group-scoped. **Zero registry rows for a persona blocks all
of these regardless of level** (which is genuinely the state for both
`vz-lupas` and `baita-conveniencia` today), so the "Missing (blocked)"
verdicts in the tables below are not themselves wrong — but the right
remediation is 3 Brand logo images + a small number of Campaign/Group
covers, **not** 94 (or however many) per-Product photos. Per-Product image
coverage is a separate, much larger, lower-priority effort that the
inheritance fallback already partially covers once any Group-level or
sibling-Product asset exists.

## 3. Per-persona gap checklist

### 3a. `vz-lupas`

| Requirement | Status | What's missing |
|---|---|---|
| Active `graph_publication` (v3) | **Missing** | None has ever been staged. This is the precondition for everything else. |
| `persona:self` staging hazard | **Missing / blocking** | Roadmap (`AGENT_ROADMAP.md`, "Dívida operacional de produção", item 6) records `vz-lupas` at 4/4 active edges on the duplicate `persona:self` node, and explicitly marks it **not archivable**. `stage_bundle` compiles the whole database post-write and will abort with `materialized_runtime_checksum_mismatch` the same way it did for Tock Fatal's v16 — except Tock could archive its (all-inactive) `persona:self` edges and `vz-lupas` cannot. Needs either (a) migrating those 4 active edges onto the bundle's own persona node, or (b) the "resident rows" parameter the roadmap proposes for `build_publication_plan`/`compile_bundle`. Neither exists yet. |
| Publication identity fields | **Unknown** | Depends entirely on the bundle that would be authored; nothing to check yet since no bundle/publication exists. |
| `gallery` node + `publishes_to` wiring | **Unknown** | 1 gallery node exists, but whether any node has a `publishes_to` edge into it is not in the production snapshot — must be verified before assuming any grant works. |
| `persona.data.public_site.slug/name/format_key/default_collection_slug/brand_family/brand_channel` | **Unknown/likely missing** | No evidence this object has been authored on the persona node at all. |
| `whatsapp.phone` / `whatsapp.message_template` | **Unknown** | Same — needs to be authored on `public_site`. |
| `identity.logo_round` / `logo_wordmark` / `logo_reverse` | **Missing (blocked)** | 0 asset nodes exist for `vz-lupas`. All three are hard-required with no partial credit. Even if 3 asset nodes were authored today, they cannot resolve: the `assets` registry table has rows for only `tock-fatal` (17) and `aurora` (11) platform-wide — zero for `vz-lupas` — and the `assets-raw` storage bucket has only `tock-fatal`'s folder. This needs the full chain built from nothing: files uploaded to storage → registry rows created → graph `asset` nodes authored → `publishes_to` edges granted. |
| `pages[]` (≥2) | **Missing** | Only 1 `campaign` node exists total for `vz-lupas`. Pages need `campaign` nodes with `kind ∈ {linktree, showcase}`; at minimum 2 distinct campaign nodes are needed just for this, separate from the one needed for `locations[]`. |
| `contacts[]` (≥1) | **Missing** | Requires a `copy` node. `vz-lupas` has 0 copy nodes. |
| `covers[]` (≥1) | **Missing (blocked)** | Same asset-chain blocker as the logo kit — 0 asset nodes, no registry rows, no storage files. |
| `audiences[]` (≥1) | **Met (count-wise)** | 2 audience nodes exist. Still needs each to carry `label` + `message_template` and be granted — unverified, but the raw material exists, unlike assets/copy. |
| `locations[]` (≥1) | **Missing** | Needs a `campaign` node with `campaign_subtype == "physical_store"`, valid coordinates, and a public `google_maps_url`. Only 1 campaign node exists total and it must also cover the 2 pages above — the numbers don't add up with a single node. |
| Catalog: 1 `brand` | **Met (count-wise)** | 1 brand node exists; granting/content still unverified. |
| Catalog: products linked to groups | **Unknown** | 94 products / 14 product_groups exist; whether the linking edges (`product_group_has_product` etc.) exist and whether both sides are granted is unverified. |
| Catalog: category + product CTAs | **Unknown** | No CTA authoring state was reported. |
| Offers | **Likely acceptable if inline price data exists** | 0 offer nodes, but the code falls back to price data on the product node itself — needs to be confirmed products carry that data. |

**Headline blocker for `vz-lupas`:** it has authored zero assets and zero
copy nodes, which makes the identity kit, covers, and contacts sections of
the site contract unsatisfiable as written — on top of never having staged a
v3 bundle at all, and sitting on an unresolved `persona:self` staging hazard
that will abort the first attempt regardless of content readiness.

### 3b. `baita-conveniencia`

| Requirement | Status | What's missing |
|---|---|---|
| Active `graph_publication` (v3) | **Missing** | Same as `vz-lupas` — never staged. |
| `persona:self` staging hazard | **Missing / blocking, worse than vz-lupas** | Roadmap reports 73 total / **17 active** edges on `persona:self` for `baita-conveniencia`, also marked not archivable. More live structure is riding on the duplicate node than for `vz-lupas` (4 active), so the migration-or-resident-rows fix is a larger unit of work here. |
| `gallery` node + `publishes_to` wiring | **Unknown** | 1 gallery node exists; wiring unverified. |
| `persona.data.public_site` required fields | **Unknown/likely missing** | No evidence of authoring. |
| `identity.logo_round/wordmark/reverse` | **Missing (blocked), and misleadingly so** | 12 asset nodes exist, but all 12 are hollow: 9 carry a `registry_id` that points at `assets` rows which do not exist, 3 have no `asset_id` at all, and there are zero files in storage for this persona. `_asset_registry_id` will return a value for 9 of them, so a shallow node count ("12 assets!") looks like progress, but `_published_assets_by_registry` will resolve **none** of them because the `assets` table has zero rows for `baita-conveniencia`. Net result is identical to `vz-lupas`'s zero, but harder to detect from the graph alone. |
| `pages[]` (≥2), `locations[]` (≥1) | **Missing** | Only 1 campaign node total, same structural shortfall as `vz-lupas`. |
| `contacts[]` (≥1) | **Unknown, plausible** | 403 `copy` nodes exist — raw material is present, but need confirmation at least one carries `key`/`label`/`phone`/`message_template` and is granted. |
| `covers[]` (≥1) | **Missing (blocked)** | Same broken asset chain as the identity kit. |
| `audiences[]` (≥1) | **Met (count-wise)** | 4 audience nodes exist. |
| Catalog: 1 `brand` | **Met (count-wise)** | 1 brand node exists. |
| Catalog: product_group linkage | **Partially blocked** | 16 real `product_group` nodes exist, but 15 more groupings are still typed as legacy `category` and 1 as `product_collection`. `_compiled_catalog_payload`'s `group_nodes` dict filters strictly on `node_type == "product_group"` — the 15 `category` nodes are **invisible to v3 compilation**, full stop. Any product linked only to a `category` node (not also to a real `product_group`) will fail `published_group_relation_required` once v3 goes live. This needs either a migration of those 15 nodes to `product_group` (mirroring the historical `product_collection → product_group` canonicalization the code comments reference at menu.py:1660) or re-pointing their products onto existing `product_group` nodes. |
| FAQ (403) / Copy (403) | **Unknown — flag the coincidence** | Identical counts (403/403) across two structurally different node types is unusual enough to warrant a direct check that these weren't double-counted or mislabeled during ingestion, before relying on either number as "content is ready." |
| Offers | **Likely acceptable if inline price data exists**, same caveat as `vz-lupas` | 0 offer nodes. |

**Headline blocker for `baita-conveniencia`:** its asset pipeline is not
merely empty but actively broken — 12 nodes that look like published media
but resolve to nothing — and roughly half of its group-like nodes (15 of 31)
are on a legacy type the v3 compiler does not recognize at all. Both defects
hide behind node counts that look healthier than `vz-lupas`'s.

### 3c. Blockers shared by both personas

1. **No `graph_publication` has ever been activated for either persona.**
   Every checklist item above is untested against the real compiler until a
   bundle is built and staged.
2. **`persona:self` staging hazard** (`AGENT_ROADMAP.md`, "Dívida
   operacional de produção — aberta em 2026-09-05", item 6): neither persona
   can archive the duplicate `persona:self` node's active edges the way
   Tock Fatal did, so the first `stage_bundle` attempt for either one is
   expected to abort with `materialized_runtime_checksum_mismatch` **after**
   writing nodes/edges — leaving raw graph rows ahead of the (nonexistent)
   active publication. This is unresolved in the roadmap as written; only
   Tock Fatal's instance of the underlying bug was fixed.
3. **The `assets` registry + storage bucket only cover two personas
   platform-wide** (tock-fatal, aurora). Neither `vz-lupas` nor
   `baita-conveniencia` has a single row in `assets` or a folder in
   `assets-raw`. This blocks the identity kit and covers for both personas
   regardless of what the knowledge graph itself contains — it is
   infrastructure-level, not content-level.
4. **Only 1 `campaign` node exists for each persona**, but the site contract
   needs campaign nodes for both `pages[]` (≥2, `kind ∈ {linktree,
   showcase}`) and `locations[]` (≥1, `campaign_subtype ==
   "physical_store"`). At minimum 2 more campaign nodes are needed per
   persona even before considering whether a single node could serve double
   duty.

## 4. Should the v3 site contract become `format_key`-sensitive?

**Assessment: yes, the contract should branch on `format_key` — the current
code does not, and that is the root cause of most of the structural gaps
above, not the personas' content maturity.**

Evidence from the code:

- `format_key` is read and required as a plain non-empty string
  (`_required_text(root, "format_key", "site", errors)`, menu.py:900) and is
  round-tripped into the payload — but it is **never branched on**. A
  repository-wide search of `menu.py` for `format_key ==` / `if format_key`
  returns nothing. Every requirement in §2b (`pages ≥2`, `locations ≥1`,
  `audiences ≥1`, `covers ≥1`, the three-logo identity kit,
  `focal_point.desktop == "full"` / `mobile == "split-halves"`, the
  `showcase`-page `sections` block) applies uniformly regardless of which of
  the three registered formats (`cardapio`, `landing_page`,
  `catalogo_roupas`, per `docs/public-site-output-contract.md`) the persona
  declares.
- Every one of those unconditional requirements reads like it was shaped
  around `tock-fatal`, which is a multi-branch (`varejo`/`atacado`) fashion
  catalog with distinct palettes, a linktree-style landing page **and** a
  showcase page (hence needing ≥2 pages), audience-segmented messaging, and
  a full brand identity kit befitting a fashion label. `vz-lupas` (also
  apparel/eyewear, `catalogo_roupas`-shaped) is a reasonable fit for the same
  shape of contract. `baita-conveniencia` is a convenience store on
  `cardapio` — its natural public surface is closer to "one page: what we
  sell, a phone number, maybe a map pin." Forcing it through the same
  ≥2-pages / ≥1-location / three-logo-variant contract as a fashion label
  means authoring a `linktree` page, a `showcase` page with full
  `audiences`/`groups`/`final_cta` copy blocks, a `physical_store` location
  with map styling, and a round/wordmark/reverse logo trio — none of which a
  convenience-store owner is likely to have on hand or benefit from
  maintaining, and all of which currently 503 the *entire* public site
  (menu, prices, WhatsApp CTA included) if even one piece is missing,
  because the contract fails closed with no partial payload.
- The evidence is not that the contract is *wrong* for `catalogo_roupas`,
  it's that it is currently the **only** shape available, and it fails
  closed. For `cardapio`, the same fail-closed design that protects Tock
  Fatal's brand consistency instead means: a corner store cannot publish a
  menu without also producing fashion-brand-grade marketing collateral it
  has no use for.

**Trade-offs of making `format_key` sensitive:**

- *For:* lets a `cardapio` persona ship with a minimal, honest contract
  (e.g. 1 page, 0 required locations, a single square logo instead of three
  variants) — matching effort to what the format actually renders. Keeps the
  fail-closed guarantee, just with a smaller required set per format.
- *For:* avoids the alternative failure mode already visible in this
  data — personas inventing placeholder pages/locations/logos purely to
  satisfy a contract shaped for a different business, which pollutes the
  graph with fictional content (a fake second "page," a copy-pasted
  logo_reverse) that then has to be maintained and could leak into customer
  copy.
- *Against:* branching validation by format multiplies the surface area
  QA/proof has to cover — "≥2 pages for catalogo_roupas, ≥1 page for
  cardapio" is two contracts to test, not one, and the failure-closed
  guarantee is only as strong as the per-format rule someone remembers to
  write. `public_site_formats` rows would need to carry (or reference) their
  own minimums, and every reader of `menu.py` needs to know the requirement
  set is no longer a flat list.
- *Against:* until `landing_page` also has a live persona, there is only one
  real data point (`tock-fatal`/`catalogo_roupas`) to validate any
  format-specific ruleset against — a `cardapio`-specific contract designed
  now, before `baita-conveniencia` or `vz-lupas` ship, risks being shaped by
  guesswork the same way the current uniform contract was shaped by
  `tock-fatal` alone.

Recommendation for the architectural decision this feeds: treat
`format_key`-sensitivity as the right direction, but derive the `cardapio`
minimum set from an actual `baita-conveniencia` launch conversation (what
does a convenience-store owner actually have — one phone number, one
address, a logo?) rather than guessing a second uniform contract from the
code alone.

## 5. Contradictions / findings worth flagging separately

- No contradiction found between `menu.py`'s code and
  `AGENT_ROADMAP.md`'s `persona:self` section — the edge counts given in the
  task brief (`vz-lupas 4/4`, `baita-conveniencia 73/17`, `aurora 19/4`,
  `tock-fatal 1012/0`) match the roadmap table at
  `docs/roadmaps/AGENT_ROADMAP.md:1109-1114` exactly (total edges / active
  edges, in that order). The roadmap is accurate on this point and should be
  trusted as-is.
- The roadmap item is explicit that item 6 (`persona:self`) remains
  **unresolved** for every persona except `tock-fatal` — there is no
  "resolvida" marker on it the way there is on the adjacent item 5. Any
  planning document that assumes `vz-lupas`/`baita-conveniencia` can stage a
  bundle today without touching `persona:self` first would be wrong.
