# VZ Lupas Graph Rebuild Definition of Done

## Current Unresolved Problem

The VZ Lupas graph rebuild is not resolved from the user's perspective.

Recent tests and refactors are not sufficient if the user still does not see the expected VZ Lupas graph in the frontend. A passing fixture-driven test does not prove that the real product outcome exists.

The expected product outcome is:

- the database contains the rebuilt VZ Lupas graph
- the backend returns the rebuilt graph through the real graph APIs
- the frontend renders the rebuilt graph
- E2E validation fails if the frontend graph is empty
- the graph is hierarchical and structured
- VZ Lupas appears with 3 Product Groups and 9 Products
- every Product has an Asset
- FAQ nodes are connected to Products
- Embed nodes are created only from approved FAQs

The product is not solved until the VZ Lupas hierarchical graph is visible in the frontend with 3 Product Groups, 9 Products, assets for every Product, precise structured edges, and validation passing in database, backend and frontend.

## Why Fixture-Only Tests Are Not Enough

Fixture-only tests can validate isolated assumptions, but they do not prove the real VZ Lupas graph generation flow works end to end.

They do not prove that:

- existing VZ Lupas graph data can be deleted and recreated safely in dev/test scope
- Sofia's real graph generation pipeline creates the expected hierarchy
- the graph is persisted correctly
- the backend reads the persisted graph correctly
- Tree View and Graph View APIs apply the correct edge rules
- the frontend renders the real graph returned by the backend
- the frontend fails visibly when the graph is empty or malformed
- products have validated Asset relationships

A fixture test may pass while the user still sees an empty or incorrect graph. That state is unresolved.

## Expected VZ Lupas Graph Structure

The final VZ Lupas graph must contain:

- 1 Persona: `vzlupas`
- 1 Brand: `VZ Lupas`
- 1 Briefing
- 1 Campaign
- 1 Audience
- 3 Product Groups
- 9 Products total
- 3 Products per Product Group
- at least one Asset for every Product
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

Assets must be connected as media/reference nodes:

```txt
Product
-> Asset
-> Gallery
```

If the existing project convention uses a different Asset/Gallery relationship, that convention is acceptable only if the relationship is consistent, validated, and does not make Asset or Gallery the main parent of knowledge hierarchy nodes.

## Required Database Validation

The database must prove:

- nodes exist for VZ Lupas
- edges exist for VZ Lupas
- there are exactly 3 Product Groups
- there are exactly 9 Products
- each Product Group has exactly 3 Products
- every Product has at least one Asset
- each Product belongs to exactly one Product Group
- every FAQ belongs to a Product
- every Embed comes only from an approved FAQ
- no forbidden edges exist

Database validation must read persisted state, not in-memory generation output only.

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
- 3 Product Groups are visible
- 9 Products are visible
- Product assets are visible or linked
- hierarchy is readable
- no floating hierarchy nodes exist
- no duplicated root hierarchy exists

The frontend is part of the definition of done. A backend-only or fixture-only success is not enough.

## Required E2E Validation

The E2E test must fail if:

- frontend graph is empty
- backend returns an empty graph
- database has no VZ Lupas nodes
- Products do not have Assets
- there are not exactly 3 Product Groups and 9 Products
- any Product Group does not have exactly 3 Products
- forbidden edges exist
- an Embed is created from anything other than an approved FAQ

The E2E path must validate database state, backend responses, frontend rendering, graph hierarchy, edge semantics, and asset relationships.

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
- VZ Lupas does not show exactly 3 Product Groups and 9 Products
- Products have no Assets
- forbidden edges exist
- Tree View rules fail
- Graph View rules fail

Deployment is allowed only after database, backend, frontend, and E2E validations pass against the real VZ Lupas graph rebuild flow.

## Final Definition of Done

This work is done only when all of the following are true:

- CEO / Product Owner confirms fixture passing is not sufficient
- VZ Lupas graph data is rebuilt in dev/test scope
- database contains the rebuilt VZ Lupas graph
- database proves exactly 3 Product Groups and 9 Products
- database proves every Product has at least one Asset
- database proves every Product belongs to exactly one Product Group
- database proves every FAQ belongs to a Product
- database proves every Embed comes only from an approved FAQ
- backend graph endpoint returns a non-empty VZ Lupas graph
- Tree View endpoint returns only main edges
- Graph View endpoint returns main and reference edges
- frontend visibly renders the VZ Lupas graph
- frontend visibly shows 3 Product Groups and 9 Products
- frontend shows or links Product Assets
- E2E fails if database, backend, or frontend graph is empty
- E2E fails on forbidden edges
- E2E fails on missing Product Assets
- E2E fails if Embed is created from anything other than an approved FAQ
- build and tests pass
- QA Lead approves the release gate
- PR & Deploy Agent deploys only after all validations pass

## Recommended Next Execution

1. CEO defines officially that fixture passing is not enough.
2. Codex writes this Definition of Done in the repo.
3. QA/E2E Validator runs BRA-8 with `BaseUrl` and `FrontendBaseUrl`.
4. If frontend is empty, assign Frontend Agent.
5. If backend is empty, assign Backend Engineer.
6. If schema is insufficient, assign Graph Validator + Migration Agent.
7. Only after all validations pass, assign PR & Deploy Agent.
