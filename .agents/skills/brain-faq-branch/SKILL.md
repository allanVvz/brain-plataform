---
name: brain-faq-branch
description: Generate, review, or repair commercial Copy and FAQ branches in Brain AI, including safe bulk FAQ proposals and approved FAQ projection to Embedded. Use for FAQ coverage, retrieval gaps, product/media questions, or broken FAQ graph hierarchy.
---

# Brain FAQ Branch

Use the active GraphBundle/Graph JSON as the factual authority. Read
`references/branch-contract.md` before changing graph content. For bulk
generation or an Embedded projection, also read
`references/bulk-embedded-contract.md`.

## Core workflow

1. Resolve the persona and the lowest factual anchor: Copy, Product, Offer,
   ProductGroup, Audience, Campaign, Brand, then Persona.
2. Generate questions from verified branch facts and real retrieval gaps. Do
   not invent price, stock, shipping cost, delivery deadline, payment, return,
   store address, image availability, or policy.
3. Preserve source node, source type, branch path, source/status and aliases on
   every FAQ proposal. Deduplicate by normalized question, intent and factual
   answer, not only by slug.
4. New model-generated FAQs remain `pending_validation`. Human-approved FAQs
   become `validated`/`approved` and receive exactly one `FAQ -> Embedded`
   projection.
5. Run GraphBundle validation and a retrieval coverage audit before preparing
   a PublicationPlan. Never publish or activate from this skill.

## Conversation quality

- Write customer-facing language, not graph vocabulary. Avoid phrases such as
  “grupo de produtos”, “opções publicadas”, “branch”, “node” or “retrieval”.
- Prefer short, specific answers and natural customer aliases.
- Keep an internal instruction in Tone/Rule nodes; do not disguise it as a FAQ
  answer.
- For photos, distinguish explicit approved-asset evidence from absence of an
  asset. An agent may offer a photo only when the exact item has approved media.
  Without that evidence, mention a human who can provide a photo only after the
  customer asks for one.
- Freight values and delivery commitments require published evidence; otherwise
  state that a specialist will confirm them.

## Asset boundary

Assets are not FAQ content. Preserve one commercial parent for each asset and
the secondary `Asset -> Gallery` relation. A FAQ may describe media availability
only when its source path proves the exact approved asset.

