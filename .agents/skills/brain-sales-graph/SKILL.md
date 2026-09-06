---
name: brain-sales-graph
description: Build or repair graph-backed sales qualification policies for Brain personas. Use when a sales persona needs purchase-profile branches, customer-name capture, qualification degree, fulfillment questions, agentic tone, or handoff rules; do not use for appointment scheduling policies.
---

# Brain Sales Graph

Make the published graph authoritative for sales qualification without turning
the conversation into a form.

## Contract

1. Confirm `persona.data.business_model=sales`.
2. Put identity facts that survive future purchases, such as `nome_cliente`, in
   `persona.data.qualification.fields` with `validation.semantic_type=human_full_name`.
3. Use a purchase-profile field to choose commercial audiences such as retail
   or resale. Do not model audiences, categories or products as “services”, and
   do not add a service selector to a sales persona.
4. Give every required field one approved qualification FAQ and a stable
   `question_node_id`. Dependencies express eligibility, not a fixed script.
5. Make the name eligible after commercial intent/profile is understood and
   make downstream branch questions depend on it when the operator requires the
   name before the final qualification. A persisted name is never asked again.
6. Model qualification degree with an operator-approved field such as purchase
   readiness. Model fulfillment separately (shipping, store visit or undecided)
   when it changes the handoff.
7. The model acknowledges and answers first, then chooses at most one natural
   eligible question. It must set `asked_field_key` whenever it asks a graph
   field and extract every fact the current message provides.
8. Before any conversational handoff, the public reply announces that a human
   will continue. Freight, stock and other unpublished operational values are
   promises for specialist confirmation, never AI confirmations.

## Tone and identity

Publish concrete Tone/Rule guidance: the assistant introduces itself as an AI
on the first reply, uses the persona's name, avoids internal graph vocabulary,
does not repeat catalog descriptions or photo offers, and speaks in short,
gentle turns. Put examples and forbidden phrases in the graph-owned guidance,
not in customer-specific runtime branches.

## Validation

Require:

- no field key representing a service selector when `business_model=sales`;
- exactly one persona-owned name field and question;
- unique field keys and question ids;
- every dependency names a declared field;
- every required field has an approved question;
- a pre-handoff notice policy;
- WA Validator scenarios for first introduction, name once, flexible multi-fact
  extraction, retail/resale isolation, shipping/store choice, photo available,
  photo unavailable, repetition recovery and handoff notice.

Do not strengthen the proof checker to compensate for missing authored content.
Fix the GraphBundle, canonical n8n prompt or field flow first. Preserve proof,
persona isolation and exactly-once invariants.

