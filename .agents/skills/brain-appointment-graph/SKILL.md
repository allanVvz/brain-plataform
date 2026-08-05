---
name: brain-appointment-graph
description: Build, review, or repair graph-backed appointment qualification policies for Brain personas and Sofia graph construction. Use when a persona needs appointment_policy.required_fields, field_questions, service-specific booking fields, qualification questions, or validation failures caused by missing graph-owned questions.
---

# Brain Appointment Graph

Make the published Graph JSON the only authority for qualification fields and questions.

## Contract

Preserve this chain:

`published persona node -> appointment_policy.required_fields -> appointment_policy.field_questions -> runtime missing_fields -> next graph question`

The backend iterates this contract. It must not invent field names or commercial questions.

## Construct with Sofia

1. Resolve the target persona and confirm `business_model=appointment`.
2. Inspect the existing persona policy and each service/product `booking.required_fields`.
3. Ask the operator which facts are required for every request and which are service-specific. Do not infer commercial qualification requirements from the persona name or market.
4. Collect one exact, operator-approved question for every distinct required field.
5. Write the ordered common fields to `persona.data.appointment_policy.required_fields`.
6. Write questions to `persona.data.appointment_policy.field_questions` using identical keys.
7. Put service-specific ordered fields in `product.data.booking.required_fields`; every one must also exist in the persona question map.
8. Preserve source, validation status and existing policy fields/texts.
9. Run graph validation before proposing publication.

## Validation

Reject publication when:

- `required_fields` is absent, empty or contains an empty key;
- `field_questions` is absent or not an object;
- a common or product-specific required field has no non-empty question;
- a runtime or n8n change embeds a fixture question as fallback/condition;
- model output selects the next question without deterministic reconciliation.

Test behavior by deriving the assertion dynamically:

```python
pending = result.state["missing_fields"][0]
expected = appointment_policy["field_questions"][pending]
assert result.reply.endswith(expected)
```

Fixture literals may prove a fixture, but must never become production decision logic.

## Handoff to E2E

After a valid graph is published, use `$brain-agent-e2e` and `/validate-brain-agent-e2e` to prove each required field advances exactly once through the real transport.
