-- Global production purge of leads and conversational runtime state.
-- Scope: every persona and channel. Knowledge, personas, campaigns, bindings,
-- graph publications and system_events are intentionally preserved.
--
-- Required operational order:
--   1. safety-pause every active binding;
--   2. stop the workers service;
--   3. run a read-only count/FK audit;
--   4. run this file with psql and the exact confirmation token;
--   5. verify zero counts before resuming any binding/worker.
--
-- Invocation:
--   psql ... -v ON_ERROR_STOP=1 \
--     -v confirmation=DELETE_ALL_LEADS_AND_CONVERSATIONS \
--     -f purge_all_leads_and_conversations.sql

\pset pager off

\if :{?confirmation}
\else
  \echo 'ABORT: pass -v confirmation=DELETE_ALL_LEADS_AND_CONVERSATIONS'
  \quit
\endif

select :'confirmation' = 'DELETE_ALL_LEADS_AND_CONVERSATIONS' as authorized \gset
\if :authorized
\else
  \echo 'ABORT: invalid confirmation token'
  \quit
\endif

begin;

-- No active transport may be able to process rows during a global reset.
do $$
declare
  unsafe_bindings integer;
begin
  select count(*) into unsafe_bindings
  from public.workflow_bindings
  where active
    and (
      connection_status <> 'safety_paused'
      or not coalesce((metadata->>'safety_paused')::boolean, false)
    );

  if unsafe_bindings <> 0 then
    raise exception 'ABORT: % active binding(s) are not safety-paused', unsafe_bindings;
  end if;
end
$$;

-- The webhook may still receive an inbound while transport is paused. These
-- locks make that inbound wait until this transaction completes, so it becomes
-- the first row of a genuinely new cycle rather than being partly deleted.
lock table
  public.agent_logs,
  public.n8n_executions,
  public.assets,
  public.campaign_recipients,
  public.contact_consents,
  public.conversation_turn_proofs,
  public.conversation_facts,
  public.conversation_ledger_branches,
  public.conversation_ledgers,
  public.conversation_journeys,
  public.sales_conversions,
  public.lead_audience_memberships,
  public.lead_import_rows,
  public.lead_buffer,
  public.messages,
  public.chat_history,
  public.knowledge_edges,
  public.knowledge_nodes,
  public.leads
in access exclusive mode;

-- Conversation nodes are operational history, but they must never be removed
-- if they were unexpectedly promoted into snapshots/RAG/validation evidence.
do $$
declare
  protected_refs integer;
begin
  select
      (select count(*)
       from public.approved_knowledge_snapshots aks
       where aks.root_node_id in (select id from public.knowledge_nodes where node_type = 'conversation')
          or aks.source_node_id in (select id from public.knowledge_nodes where node_type = 'conversation'))
    + (select count(*)
       from public.graph_validation_events gve
       where gve.source_node_id in (select id from public.knowledge_nodes where node_type = 'conversation')
          or gve.target_node_id in (select id from public.knowledge_nodes where node_type = 'conversation'))
    + (select count(*)
       from public.knowledge_rag_entries kre
       where kre.source_node_id in (select id from public.knowledge_nodes where node_type = 'conversation'))
    + (select count(*)
       from public.knowledge_rag_chunks krc
       where krc.source_node_id in (select id from public.knowledge_nodes where node_type = 'conversation'))
  into protected_refs;

  if protected_refs <> 0 then
    raise exception 'ABORT: conversation nodes have % protected graph/RAG reference(s)', protected_refs;
  end if;
end
$$;

select 'before' as phase, 'leads' as table_name, count(*) as rows from public.leads
union all select 'before', 'messages', count(*) from public.messages
union all select 'before', 'lead_buffer', count(*) from public.lead_buffer
union all select 'before', 'conversation_journeys', count(*) from public.conversation_journeys
union all select 'before', 'conversation_ledgers', count(*) from public.conversation_ledgers
union all select 'before', 'conversation_ledger_branches', count(*) from public.conversation_ledger_branches
union all select 'before', 'conversation_facts', count(*) from public.conversation_facts
union all select 'before', 'conversation_turn_proofs', count(*) from public.conversation_turn_proofs
union all select 'before', 'sales_conversions', count(*) from public.sales_conversions
union all select 'before', 'assets', count(*) from public.assets
union all select 'before', 'knowledge_nodes:conversation', count(*) from public.knowledge_nodes where node_type = 'conversation'
order by table_name;

-- Non-FK mirrors/logs must be filtered while the lead identities still exist.
delete from public.agent_logs
where lead_id in (select id::text from public.leads)
   or lead_id in (select lead_id from public.leads where lead_id is not null);

delete from public.n8n_executions
where lead_id in (select id::text from public.leads)
   or lead_id in (select lead_id from public.leads where lead_id is not null);

-- Runtime state, in reverse dependency order.
delete from public.conversation_turn_proofs;
delete from public.conversation_facts;
delete from public.conversation_ledger_branches;
delete from public.sales_conversions;
delete from public.conversation_ledgers;
delete from public.conversation_journeys;

-- Channel, consent, import and raw-message history.
delete from public.assets;
delete from public.lead_buffer;
delete from public.campaign_recipients;
delete from public.contact_consents;
delete from public.lead_audience_memberships;
delete from public.lead_import_rows;
delete from public.messages;
delete from public.chat_history;

-- Remove only operational conversation nodes. Canonical graph content remains.
delete from public.knowledge_edges
where source_node_id in (select id from public.knowledge_nodes where node_type = 'conversation')
   or target_node_id in (select id from public.knowledge_nodes where node_type = 'conversation');
delete from public.knowledge_nodes where node_type = 'conversation';

delete from public.leads;

do $$
declare
  remaining bigint;
begin
  select
      (select count(*) from public.leads)
    + (select count(*) from public.messages)
    + (select count(*) from public.lead_buffer)
    + (select count(*) from public.conversation_journeys)
    + (select count(*) from public.conversation_ledgers)
    + (select count(*) from public.conversation_ledger_branches)
    + (select count(*) from public.conversation_facts)
    + (select count(*) from public.conversation_turn_proofs)
    + (select count(*) from public.sales_conversions)
    + (select count(*) from public.assets)
    + (select count(*) from public.knowledge_nodes where node_type = 'conversation')
  into remaining;

  if remaining <> 0 then
    raise exception 'ABORT: post-cleanup verification found % remaining row(s)', remaining;
  end if;
end
$$;

select 'after' as phase, 'leads' as table_name, count(*) as rows from public.leads
union all select 'after', 'messages', count(*) from public.messages
union all select 'after', 'lead_buffer', count(*) from public.lead_buffer
union all select 'after', 'conversation_journeys', count(*) from public.conversation_journeys
union all select 'after', 'conversation_ledgers', count(*) from public.conversation_ledgers
union all select 'after', 'conversation_facts', count(*) from public.conversation_facts
union all select 'after', 'conversation_turn_proofs', count(*) from public.conversation_turn_proofs
union all select 'after', 'assets', count(*) from public.assets
union all select 'after', 'knowledge_nodes:conversation', count(*) from public.knowledge_nodes where node_type = 'conversation'
order by table_name;

commit;
