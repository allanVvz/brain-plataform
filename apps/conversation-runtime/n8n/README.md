# Legacy conversation workflow fixture

`persona-conversation-template.json` is retained for audit and regression
comparison. It is not provisionable and must not be activated for the current
conversation path. The template contains historical model, repair, proof and
commit nodes that would duplicate the production decision.

The active path calls the persona's configured model twice from
`apps/conversation-runtime/api/services/agentic_turn.py`: first to understand
the inbound, then to write the reply from the published graph and current
journey. The runtime validates publication and persona identity, persists the
accepted ledger and proof, and commits at most one internal outbound per
canonical inbound. n8n can run separate transport or auxiliary automations;
it does not execute synchronous conversation decisions.
