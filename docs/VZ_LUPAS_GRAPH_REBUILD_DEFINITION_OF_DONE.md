# VZ Lupas Graph Rebuild Definition of Done

> **Revised 2026-09-12.** The original version of this document (below its
> history is preserved in git) defined success as "exactly 3 Product Groups
> and 9 Products, every Product has an Asset." Production reality is **14
> Product Groups and 94 Products, and zero Assets** — the fixed counts and
> the "every Product has an Asset" gate were never true of the rebuilt graph
> and had become actively misleading: a validator built against them would
> either block a correct graph forever or need to be silently bypassed,
> either of which defeats the point of a Definition of Done. See
> `docs/reports/v3-readiness-vz-baita.md` for the full gap analysis this
> rewrite is based on.
>
> What changed and why:
> - **Removed** every fixed count ("3 Product Groups", "9 Products", "3
>   Products per Group"). The hierarchy rule (Persona → Brand → ... →
>   Product Group → Product) does not require specific counts, and pinning
>   the DoD to counts that do not match the authored catalog was the root
>   cause of the document going stale the moment content grew.
> - **Removed** "every Product has an Asset" as a *passing* criterion.
>   Production has 0 asset nodes for VZ Lupas today, and the platform-wide
>   `assets` registry table has zero rows and zero storage files for this
>   persona — image coverage is not close to done, and there is no test
>   that can honestly pass while claiming otherwise. It is now tracked
>   explicitly as an **open content gap**, not folded into pass/fail.
> - **Kept** everything about hierarchy shape, FAQ-belongs-to-Product,
>   Embed-only-from-approved-FAQ, and "E2E must fail on an empty/malformed
>   graph" — these rules do not depend on how many products or groups exist,
>   and nothing in the current state contradicts them.
> - **Kept** the voice and structure of the original (the failure
>   classification list, the agent ownership table, the fixture-vs-real
>   distinction) wherever it did not depend on the stale counts.

> **Correction 2026-09-12 (same day).** The revision above still described the
> asset model as a single `Product -> Asset -> Gallery` chain and framed
> "every Product has an Asset" as the only gate worth removing. Both are
> wrong about the actual model, verified against
> `apps/control-plane/api/routes/menu.py`
> (`_compiled_catalog_payload`/`_canonical_site_from_publication`) and
> `packages/brain-contracts/brain_contracts/catalog_media.py`
> (`resolve_catalog_media`), which is the authoritative source per
> `AGENTS.md`.
>
> The real model: an Asset can attach to a **Brand**, a **Campaign**, a
> **Product Group** (`category_has_asset`), or a **Product** (`uses_asset`)
> — four distinct owner types, not one. It also serves two distinct
> purposes that read from different edges:
> - **Public site identity/covers** (`menu.py`): the 3-logo identity kit and
>   `covers[]`/banners are **Brand**- and **Campaign**-scoped, not
>   per-Product. A Product Group's cover falls back to the first Product
>   asset found under it only if the group has no cover of its own
>   (`menu.py:780-781`) — so a handful of correctly-placed Brand/Campaign
>   assets satisfies identity and covers without any Product ever getting
>   an image.
> - **Conversational media (WhatsApp send)** (`catalog_media.py:94-104`):
>   `resolve_catalog_media` resolves a Product's or Product Group's assets
>   with explicit **inheritance in both directions** — a Product Group with
>   no direct cover inherits from its Products' assets, so one photo at
>   either level covers the gap for the other. Brand-function assets
>   (`brand_logo`, `brand_font`, `font`, `logo`) are explicitly excluded
>   from this path (`catalog_media.py:40`) — they are identity assets, never
>   sent as product photos.
>
> Consequence for this document: "every Product has an Asset" was never the
> right minimum bar to remove — it was never a coherent bar in the first
> place, because coverage is not a per-Product property in either use case.
> The corrected sections below ("Assets, when authored, must be connected"
> and "Known Open Gap: Assets") replace the single-chain diagram and the
> Product-only closing plan.

## Current Unresolved Problem

The VZ Lupas graph rebuild is not resolved from the user's perspective.

Recent tests and refactors are not sufficient if the user still does not see
the expected VZ Lupas graph in the frontend. A passing fixture-driven test
does not prove that the real product outcome exists.

The expected product outcome is:

- the database contains the rebuilt VZ Lupas graph
- the backend returns the rebuilt graph through the real graph APIs
- the frontend renders the rebuilt graph
- E2E validation fails if the frontend graph is empty
- the graph is hierarchical and structured
- VZ Lupas appears with its real authored Product Groups and Products —
  today that is **14 Product Groups and 94 Products** (verified in
  production, 2026-09-12); this document no longer hard-codes a count, and
  whichever numbers are correct at any given time must come from the
  database, not from this file
- FAQ nodes are connected to Products
- Embed nodes are created only from approved FAQs
- image coverage (a Product having at least one Asset) is tracked as an
  **open content gap**, not a release blocker — see §"Known Open Gap:
  Assets" below

The product is not solved until the VZ Lupas hierarchical graph is visible
in the frontend with its real Product Groups and Products, precise
structured edges, and validation passing in database, backend and frontend.
Image coverage is separately tracked and does not gate this definition of
done.

## Why Fixture-Only Tests Are Not Enough

Fixture-only tests can validate isolated assumptions, but they do not prove
the real VZ Lupas graph generation flow works end to end.

They do not prove that:

- existing VZ Lupas graph data can be deleted and recreated safely in
  dev/test scope
- Sofia's real graph generation pipeline creates the expected hierarchy
- the graph is persisted correctly
- the backend reads the persisted graph correctly
- Tree View and Graph View APIs apply the correct edge rules
- the frontend renders the real graph returned by the backend
- the frontend fails visibly when the graph is empty or malformed
- products have correctly structured FAQ/hierarchy relationships

A fixture test may pass while the user still sees an empty or incorrect
graph. That state is unresolved.

## Expected VZ Lupas Graph Structure

The final VZ Lupas graph must contain:

- 1 Persona: `vz-lupas`
- 1 Brand: `VZ Lupas`
- 1 Briefing
- 1 Campaign (at minimum — see `docs/reports/v3-readiness-vz-baita.md` for
  why more may be needed once VZ Lupas moves to the GraphBundle v3
  publication contract, which needs distinct campaign nodes for pages and
  for physical-store locations)
- 1 or more Audiences
- N Product Groups, each with 1 or more Products (N and per-group counts are
  whatever the authored catalog actually contains — production is currently
  14 groups / 94 products; do not hard-code either number in tests)
- FAQ nodes connected to Products
- Embed nodes only from approved FAQs

Required hierarchy:

```txt
Persona
-> Brand
-> Briefing
-> Campaign
-> Audience
-> Product Group
-> Product
-> FAQ
-> Embed
```

Assets, when authored, attach at **any of four owner types**, not only
Product — each via its own relation type, verified against
`_compiled_catalog_payload` in `apps/control-plane/api/routes/menu.py`:

```txt
Brand         -> (brand_has_asset)    -> Asset -> Gallery   [identity kit, brand cover]
Campaign      -> (campaign_has_asset) -> Asset -> Gallery   [hero/footer banners]
Product Group -> (category_has_asset)-> Asset -> Gallery   [group cover]
Product       -> (uses_asset)        -> Asset -> Gallery   [product image]
```

One image can stand in for more than the node it is attached to: a Product
Group with no cover of its own falls back to the first cover-eligible
Product asset beneath it (site path, `menu.py:780-781`), and
`resolve_catalog_media` (`brain_contracts/catalog_media.py`) resolves a
Product Group's or Product's sendable media with inheritance in **both**
directions between the two. So "does this Product have a photo" is never
the right question on its own — "does this Product, or its Group, or (for
site identity) the Brand/Campaign have one" is. Brand-function assets
(logo, wordmark, font) are excluded from the conversational-send path; they
exist only for site identity.

If the existing project convention uses a different Asset/Gallery
relationship, that convention is acceptable only if the relationship is
consistent, validated, and does not make Asset or Gallery the main parent of
knowledge hierarchy nodes. **Note:** as of 2026-09-12, VZ Lupas has zero
Asset nodes in production, at **any** owner level (Brand, Campaign, Product
Group, or Product) — this relationship is currently unexercised for this
persona. See "Known Open Gap: Assets" below before writing a validator that
assumes any Asset edges exist.

## Required Database Validation

The database must prove:

- nodes exist for VZ Lupas
- edges exist for VZ Lupas
- every Product Group has at least 1 Product
- every Product belongs to exactly one Product Group
- every FAQ belongs to a Product
- every Embed comes only from an approved FAQ
- no forbidden edges exist

Database validation must read persisted state, not in-memory generation
output only. It must assert against **whatever counts are actually in the
database at validation time** — a hard-coded expected count (e.g. "assert
exactly 9 products") is exactly the failure mode this revision removes.
Where a specific number matters for a specific release, state it in the
release notes / PR description, not in this document or in a test literal
that will silently go stale.

## Required Backend Validation

The backend/API must prove:

- the graph endpoint returns a non-empty VZ Lupas graph
- Tree View endpoint returns only main edges
- Graph View endpoint returns main and reference edges
- backend does not return an empty graph for VZ Lupas after rebuild
- backend rejects invalid graph structures

Backend validation must use the real graph persistence and query path.

## Required Frontend Validation

The frontend must prove:

- VZ Lupas graph is visible
- all authored Product Groups and Products are visible (count matches the
  database at test time, not a fixed literal)
- Product assets are visible or linked **where they exist**; a Product with
  no Asset must render cleanly (e.g. a placeholder or no-image state), not
  as a broken or missing card — see "Known Open Gap: Assets"
- hierarchy is readable
- no floating hierarchy nodes exist
- no duplicated root hierarchy exists

The frontend is part of the definition of done. A backend-only or
fixture-only success is not enough.

## Required E2E Validation

The E2E test must fail if:

- frontend graph is empty
- backend returns an empty graph
- database has no VZ Lupas nodes
- any Product Group has zero Products
- any Product does not belong to exactly one Product Group
- forbidden edges exist
- an Embed is created from anything other than an approved FAQ

The E2E path must validate database state, backend responses, frontend
rendering, graph hierarchy, and edge semantics. It must **not** assert a
fixed Product/Product Group count and must **not** fail on a Product having
zero Assets — image coverage is an open content gap (below), not a
correctness bug, and an E2E suite that conflates the two will either block
releases forever or get its asset assertion quietly disabled, which is the
same failure this document is being rewritten to stop.

## Known Open Gap: Assets

As of 2026-09-12, VZ Lupas has **zero Asset nodes** in production, at every
owner level (Brand, Campaign, Product Group, Product). This is a content
gap, not a validation bug, and it is being tracked here explicitly so it
does not get silently reintroduced as a false "passing criterion" — and so
it does not get silently reintroduced as a **Product-only** criterion
either, which was the error in the first revision of this document.

- Closing it requires, in order and regardless of owner level: (1) image
  files uploaded to the platform's asset storage bucket for this persona
  (today the bucket has folders for no persona other than `tock-fatal`),
  (2) a corresponding row per image in the platform `assets` registry table
  with `approval_status: approved` (today that table has rows for only
  `tock-fatal` and `aurora`), (3) a graph `asset` node per image, and (4)
  the edge appropriate to what the image represents —
  `brand_has_asset` (identity kit, brand cover), `campaign_has_asset`
  (hero/footer banner), `category_has_asset` (Product Group cover), or
  `uses_asset` (Product image) — plus, if VZ Lupas moves to GraphBundle v3
  publication, a `publishes_to` edge from the asset node to the persona's
  `gallery` node.
- **These are not one undifferentiated backlog item.** The Brand-level
  identity kit is 3 images total (`logo_round`, `logo_wordmark`,
  `logo_reverse`) and unlocks the entire public site regardless of Product
  image coverage. Campaign/Product-Group covers are a handful more. Both
  are small, high-leverage units of work that should be prioritized ahead
  of per-Product coverage, which is large (94 Products) and lower-leverage
  because of the inheritance fallback described above — a Product Group
  cover or a sibling Product's photo already stands in until a Product has
  its own.
- Until that pipeline exists for VZ Lupas, neither "every Product has an
  Asset" nor "the identity kit exists" is achievable, and no test should
  assert either as a hard release gate. When asset authoring begins, track
  Product-level coverage as a percentage (e.g. "N of 94 Products have at
  least one approved Asset, directly or via inherited Group cover")
  separately from Brand/Campaign identity-kit completeness — conflating the
  two into one gate is what produced the original "every Product has an
  Asset" error.

## Agent Ownership

- CEO / Product Owner: final definition of done and priority
- QA Lead: release gate and quality decision
- QA/E2E Validator: full DB + backend + frontend E2E
- Tree/Data Architect: graph generation hierarchy
- Backend Engineer: backend graph API and persistence issues
- Frontend Agent: graph UI visibility/rendering issues
- Graph Validator + Migration Agent: schema only if proven necessary
- PR & Deploy Agent: deploy only after all validations pass

## Failure Classification

Use exactly one of these failure classes when reporting a failure:

- `database_persistence_bug`
- `backend_graph_api_bug`
- `frontend_rendering_bug`
- `graph_generation_bug`
- `validation_logic_bug`
- `layout_depth_bug`
- `asset_connection_bug`
- `database_schema_limitation`
- `environment_blocker`

## Deploy Gate

Do not deploy if:

- graph is empty
- tests fail
- build fails
- backend returns invalid graph
- frontend does not show VZ Lupas graph
- any Product Group has zero Products, or any Product belongs to more than
  one Product Group
- forbidden edges exist
- Tree View rules fail
- Graph View rules fail

Missing Product Assets does **not** block deploy on its own — it is tracked
as an open content gap (see above), not a deploy gate. If a future decision
promotes image coverage to a hard release gate (for example, before VZ
Lupas is exposed on the GraphBundle v3 public site path, which does require
resolvable product images for covers/identity), that decision must be made
explicitly and dated here, not implied by a stale counter.

Deployment is allowed only after database, backend, frontend, and E2E
validations pass against the real VZ Lupas graph rebuild flow.

## Final Definition of Done

This work is done only when all of the following are true:

- CEO / Product Owner confirms fixture passing is not sufficient
- VZ Lupas graph data is rebuilt in dev/test scope
- database contains the rebuilt VZ Lupas graph
- database proves every Product Group has at least one Product and every
  Product belongs to exactly one Product Group (no fixed count required)
- database proves every FAQ belongs to a Product
- database proves every Embed comes only from an approved FAQ
- backend graph endpoint returns a non-empty VZ Lupas graph
- Tree View endpoint returns only main edges
- Graph View endpoint returns main and reference edges
- frontend visibly renders the VZ Lupas graph
- frontend visibly shows all authored Product Groups and Products
- frontend shows or links Product Assets where they exist, and degrades
  cleanly where they do not
- E2E fails if database, backend, or frontend graph is empty
- E2E fails on forbidden edges
- E2E fails if any Product Group has zero Products or any Product belongs
  to more than one Product Group
- E2E fails if Embed is created from anything other than an approved FAQ
- build and tests pass
- QA Lead approves the release gate
- PR & Deploy Agent deploys only after all validations pass

Image coverage (Products having Assets) is explicitly **not** part of this
gate today. It is an open, tracked content gap — see "Known Open Gap:
Assets" — and pretending otherwise is what made the previous version of
this document wrong.

## Recommended Next Execution

1. CEO defines officially that fixture passing is not enough.
2. Codex writes this Definition of Done in the repo.
3. QA/E2E Validator runs the real E2E suite against the current database
   counts (do not hard-code Product/Product Group numbers into the test).
4. If frontend is empty, assign Frontend Agent.
5. If backend is empty, assign Backend Engineer.
6. If schema is insufficient, assign Graph Validator + Migration Agent.
7. Separately from this gate, scope and prioritize the Asset pipeline work
   (storage bucket, `assets` registry rows, graph asset nodes) needed to
   close the image-coverage gap — see `docs/reports/v3-readiness-vz-baita.md`.
8. Only after all validations pass, assign PR & Deploy Agent.
