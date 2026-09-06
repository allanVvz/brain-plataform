# Bulk FAQ to Embedded contract

Use this contract for multi-node or multi-question generation.

## Input matrix

Build a row for each factual anchor and gap:

- persona and active commercial branch;
- anchor node id/type and full branch path;
- verified facts and source;
- customer intent and natural query aliases;
- channel/audience visibility;
- approved media evidence for the exact product, when present;
- unknown facts that must be deferred to a specialist.

Generate coverage by intent rather than multiplying near-identical wording.
Useful intent families are description, comparison, price already published,
quantity, purchase next step, stock confirmation, freight confirmation, store
visit, photo available, photo unavailable, payment confirmation and human
handoff. Skip a family when the source does not support a safe answer.

## Output invariants

Each proposal carries:

```yaml
node_type: faq
status: pending_validation
data:
  question: "..."
  question_aliases: ["..."]
  answer: "..."
  source: "..."
  source_node_id: "..."
  source_node_type: "..."
  branch_path: ["..."]
  metadata:
    generator: "..."
    generation_batch_id: "..."
```

The proposed topology is `anchor -> FAQ`. Do not create `FAQ -> Embedded`
while status is pending. After explicit human approval, set the publishable
status and add exactly one `publishes_to` edge from that FAQ to the persona's
protected Embedded node. Fail the plan if Embedded is absent or ambiguous.

When the compiler needs publishable status and the Embedded edge inside a
sealed, non-active PublicationPlan, mark the candidate metadata
`validation_state=pending_operator_approval` and gate the edge with
`activation_gate=operator_approved_publication_plan`. This is staging syntax,
not human validation: do not stage or activate until the operator approves the
exact draft checksum. A missing or `pending_source` source blocks this path.

## Review

Reject duplicates that share the same normalized intent and answer even when
their wording differs. Reject technical language, unsupported promises,
cross-branch facts and photo offers without exact approved-asset evidence.
Return counts for proposed, deduplicated, held back and Embedded-eligible FAQs.
