# /build-appointment-graph

Use `$brain-appointment-graph` with Sofia to construct or repair an appointment persona policy without backend copy or field hardcodes.

## Arguments

- `persona_slug`: target persona (required)
- `mode`: `inspect`, `propose` or `validate` (default `inspect`)

## Workflow

1. Load the current Graph JSON and resolve its persona node.
2. Inventory `appointment_policy.required_fields`, `field_questions` and every product/service `booking.required_fields`.
3. Ask only for missing business decisions: ordered required fields and the exact question for each field.
4. Produce a surgical Sofia graph patch that preserves all unrelated persona/product data.
5. Validate that every common and product-specific field has a non-empty question.
6. Refuse publication if any mapping is incomplete; never substitute backend default text.
7. Report the proposed node patches, source/status and remaining operator questions.

This command does not publish automatically. Publication requires the normal reviewed Sofia/graph workflow.
