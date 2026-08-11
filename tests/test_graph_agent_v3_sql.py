from __future__ import annotations

import json
import uuid

import psycopg2.extras
import pytest


@pytest.fixture()
def cur(pg_conn):
    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        yield cursor


def scenario(cur):
    persona_id = str(uuid.uuid4())
    cur.execute(
        "insert into public.personas(id,slug,name) values(%s,%s,'Graph v3')",
        (persona_id, f"graph-v3-{persona_id[:8]}"),
    )
    cur.execute(
        "insert into public.leads(nome,persona_id) values('Lead',%s) returning id",
        (persona_id,),
    )
    lead_ref = cur.fetchone()["id"]
    checksum = "sha256:" + "a" * 64
    document = {
        "schema_version": "3.0",
        "coordinates": {"branch:a": {}},
        "branch_memberships": {"branch:a": {"branch:a": {}}},
        "projection_manifest": {
            "entry_count": 1,
            "chunk_count": 1,
            "branch_chunk_counts": {"branch:a": 1},
            "embedding_dimension": 1536,
        },
    }
    cur.execute(
        """
        insert into public.graph_publications(
          persona_id,version,checksum,document_json,status,compiler_version
        ) values(%s,1,%s,%s::jsonb,'compiled','test-v3') returning id
        """,
        (persona_id, checksum, json.dumps(document)),
    )
    publication_id = cur.fetchone()["id"]
    cur.execute(
        """
        insert into public.graph_node_coordinates(
          publication_id,node_id,branch_anchor_node_id,path_node_ids,path_edge_ids,depth,path_checksum
        ) values(%s,'branch:a','branch:a',array['branch:a'],array[]::text[],0,%s)
        """,
        (publication_id, checksum),
    )
    cur.execute(
        """
        insert into public.graph_branch_memberships(
          publication_id,branch_node_id,node_id,graph_distance,inclusion_reason,structural_weight
        ) values(%s,'branch:a','branch:a',0,'anchor',1)
        """,
        (publication_id,),
    )
    cur.execute(
        """
        insert into public.graph_branch_contracts(
          publication_id,branch_node_id,path_checksum,closure_checksum,contract_json,compiler_version
        ) values(%s,'branch:a',%s,%s,'{}','test-v3')
        """,
        (publication_id, checksum, checksum),
    )
    cur.execute(
        """
        insert into public.knowledge_rag_entries(
          persona_id,publication_id,source_graph_node_id,content_type,semantic_level,
          title,content,canonical_key,slug,status,projection_status
        ) values(%s,%s,'branch:a','general_note',1,'Branch','branch alpha',%s,'branch-a','validated','ready')
        returning id
        """,
        (persona_id, publication_id, f"test:{publication_id}"),
    )
    entry_id = cur.fetchone()["id"]
    cur.execute(
        """
        insert into public.knowledge_rag_chunks(
          rag_entry_id,persona_id,publication_id,source_graph_node_id,branch_anchor_node_id,
          chunk_index,chunk_text,embedding,embedding_model,embedded_at,projection_status,
          path_checksum,chunk_kind,chunk_checksum,metadata
        ) values(%s,%s,%s,'branch:a','branch:a',0,'branch alpha',
          array_fill(0::real,array[1536])::vector,'test',now(),'ready',%s,'content',%s,
          '{"path_node_ids":["branch:a"],"priority":1}'::jsonb)
        returning id
        """,
        (entry_id, persona_id, publication_id, checksum, checksum),
    )
    chunk_id = cur.fetchone()["id"]
    return persona_id, lead_ref, publication_id, checksum, chunk_id


def transport_scenario(cur):
    persona_id, lead_ref, publication_id, checksum, chunk_id = scenario(cur)
    binding_id = str(uuid.uuid4())
    cur.execute(
        """
        insert into public.workflow_bindings(
          id,persona_id,workflow_name,channel,provider,connection_status,active,metadata
        ) values(%s,%s,'Graph v3 test','whatsapp','meta_cloud','connected',true,
          '{"decision_owner":"deterministic","transport_mode":"provider_direct","runtime_version":"graph_agent_runtime_v3"}'::jsonb)
        """,
        (binding_id, persona_id),
    )
    cur.execute("update public.leads set channel_binding_id=%s where id=%s", (binding_id, lead_ref))
    correlation_id = f"corr:{uuid.uuid4()}"
    inbound_buffer = {
        "persona_id": persona_id,
        "lead_ref": lead_ref,
        "channel_binding_id": binding_id,
        "direction": "inbound",
        "payload": {"text": "hello"},
        "status": "processing",
        "batch_key": f"{persona_id}:{lead_ref}",
        "idempotency_key": f"inbound:{correlation_id}",
        "correlation_id": correlation_id,
    }
    inbound_message = {
        "lead_id": lead_ref,
        "role": "user",
        "content": "hello",
        "direction": "inbound",
        "status": "buffered",
        "channel": "whatsapp",
        "sender_id": correlation_id,
        "channel_binding_id": binding_id,
        "correlation_id": correlation_id,
    }
    cur.execute(
        "select public.enqueue_whatsapp_envelope(%s::jsonb,%s::jsonb) result",
        (json.dumps(inbound_buffer), json.dumps(inbound_message)),
    )
    inbound_id = str(cur.fetchone()["result"]["buffer_id"])
    cur.execute(
        "select public.claim_conversation_commit(%s,%s,%s,%s) result",
        (inbound_id, binding_id, lead_ref, correlation_id),
    )
    assert cur.fetchone()["result"]["state"] == "claimed"
    return {
        "persona_id": persona_id,
        "lead_ref": lead_ref,
        "publication_id": str(publication_id),
        "checksum": checksum,
        "chunk_id": str(chunk_id),
        "binding_id": binding_id,
        "correlation_id": correlation_id,
        "inbound_id": inbound_id,
    }


def atomic_payload(data, *, expected_revision=0):
    outbound_key = f"ai:{data['correlation_id']}"
    turn = {
        "canonical_inbound_id": data["inbound_id"],
        "binding_id": data["binding_id"],
        "correlation_id": data["correlation_id"],
        "persona_id": data["persona_id"],
        "lead_ref": data["lead_ref"],
        "publication_id": data["publication_id"],
        "graph_checksum": data["checksum"],
        "active_branch_node_id": "branch:a",
        "active_branch_node_ids": ["branch:a"],
        "asked_question_node_ids": ["question:a"],
        "expected_revision": expected_revision,
        "facts": [],
        "retrieval_trace": {"chunk_ids": [data["chunk_id"]]},
        "model_proposal": {"reply": "ok"},
        "proof_result": {"valid": True},
        "repair_result": {},
        "final_decision": {"intent": "test"},
    }
    outbound_buffer = {
        "persona_id": data["persona_id"],
        "lead_ref": data["lead_ref"],
        "channel_binding_id": data["binding_id"],
        "direction": "outbound",
        "payload": {"text": "reply", "sender_type": "agent"},
        "status": "awaiting_proof",
        "batch_key": f"{data['persona_id']}:{data['lead_ref']}",
        "idempotency_key": outbound_key,
        "correlation_id": outbound_key,
    }
    outbound_message = {
        "lead_id": data["lead_ref"],
        "role": "assistant",
        "content": "reply",
        "direction": "outbound",
        "status": "pending",
        "channel": "whatsapp",
        "sender_id": outbound_key,
        "channel_binding_id": data["binding_id"],
        "correlation_id": outbound_key,
    }
    return turn, outbound_buffer, outbound_message


def test_atomic_activation_hybrid_search_and_exactly_once_proof(cur):
    persona_id, lead_ref, publication_id, checksum, chunk_id = scenario(cur)
    cur.execute("select public.activate_graph_publication_v3(%s) result", (publication_id,))
    assert cur.fetchone()["result"]["status"] == "active"

    cur.execute(
        """
        select * from public.graph_hybrid_search_v3(
          %s,%s,'branch:a','alpha',array_fill(0::real,array[1536])::vector,
          array['branch:a'],array[]::text[],10
        )
        """,
        (persona_id, publication_id),
    )
    result = cur.fetchall()
    assert [row["chunk_id"] for row in result] == [chunk_id]
    assert result[0]["bm25_score"] > 0

    params = (
        "inbound:one", persona_id, lead_ref, publication_id, checksum, "branch:a",
        ["question:a"], 0,
        json.dumps([{
            "field_key": "arbitrary_field", "owner_node_id": "branch:a",
            "status": "known", "value": "value", "source_message_id": "msg-1",
            "evidence_span": "value", "confidence": 1,
        }]),
        json.dumps({"chunk_ids": [str(chunk_id)]}), json.dumps({"reply": "ok"}),
        json.dumps({"valid": True}), json.dumps({}), json.dumps({"intent": "test"}),
        "outbound:one",
    )
    cur.execute(
        """
        select public.commit_graph_turn_v3(
          %s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
          %s::jsonb,%s::jsonb,%s
        ) result
        """,
        params,
    )
    first = cur.fetchone()["result"]
    assert first["deduplicated"] is False
    cur.execute(
        """
        select public.commit_graph_turn_v3(
          %s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
          %s::jsonb,%s::jsonb,%s
        ) result
        """,
        params,
    )
    second = cur.fetchone()["result"]
    assert second["deduplicated"] is True
    assert second["proof_id"] == first["proof_id"]
    cur.execute("select count(*) count from public.conversation_turn_proofs where canonical_inbound_id='inbound:one'")
    assert cur.fetchone()["count"] == 1


def test_fact_revision_advances_across_different_owners(cur):
    persona_id, lead_ref, publication_id, checksum, _chunk_id = scenario(cur)

    def commit(inbound: str, owner: str, expected_revision: int) -> dict:
        fact = json.dumps([{
            "field_key": "servico", "owner_node_id": owner,
            "status": "known", "value": owner,
            "source_message_id": inbound, "evidence_span": owner,
            "confidence": 1,
        }])
        cur.execute(
            """
            select public.commit_graph_turn_v3(
              %s,%s,%s,%s,%s,%s,array[]::text[],%s,%s::jsonb,
              '{}'::jsonb,'{}'::jsonb,'{"valid":true}'::jsonb,
              '{}'::jsonb,'{"intent":"service"}'::jsonb,null
            ) result
            """,
            (inbound, persona_id, lead_ref, publication_id, checksum,
             owner, expected_revision, fact),
        )
        return cur.fetchone()["result"]

    first = commit("inbound:owner-a", "branch:owner-a", 0)
    second = commit("inbound:owner-b", "branch:owner-b", first["ledger_revision"])
    assert second["ledger_revision"] == first["ledger_revision"] + 1
    cur.execute(
        """
        select owner_node_id,revision,is_current
          from public.conversation_facts
         where ledger_id=%s and field_key='servico'
         order by revision
        """,
        (first["ledger_id"],),
    )
    rows = cur.fetchall()
    assert [(row["owner_node_id"], row["revision"], row["is_current"]) for row in rows] == [
        ("branch:owner-a", 1, True),
        ("branch:owner-b", 2, True),
    ]
    cur.execute("select count(*) count from public.conversation_facts where ledger_id=%s and is_current", (first["ledger_id"],))
    assert cur.fetchone()["count"] == 2


def test_atomic_turn_releases_only_after_valid_proof_and_retry_reads_completed(cur):
    data = transport_scenario(cur)
    turn, outbound_buffer, outbound_message = atomic_payload(data)
    cur.execute(
        "select public.commit_graph_turn_and_outbox_v3(%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb) result",
        (json.dumps(turn), json.dumps(outbound_buffer), json.dumps(outbound_message), json.dumps({"ok": True})),
    )
    result = cur.fetchone()["result"]
    assert result["state"] == "completed"
    assert result["outbound_status"] == "pending_send"
    outbound_id = result["outbound_buffer_id"]

    cur.execute("select public.audit_conversation_turn_v3(%s) audit", (data["inbound_id"],))
    audit = cur.fetchone()["audit"]
    assert audit["inbound_count"] == 1
    assert audit["decision_count"] == 1
    assert audit["proof_count"] == 1
    assert audit["valid_proof_count"] == 1
    assert audit["outbound_count"] == 1
    assert audit["outbound_status"] == "pending_send"
    assert audit["outbound_released_after_proof"] is True
    assert audit["commit_state"] == "completed"

    cur.execute(
        "select public.claim_conversation_commit(%s,%s,%s,%s) result",
        (data["inbound_id"], data["binding_id"], data["lead_ref"], data["correlation_id"]),
    )
    retry = cur.fetchone()["result"]
    assert retry["state"] == "completed"
    assert retry["result"]["outbound_buffer_id"] == outbound_id

    cur.execute("select * from public.claim_whatsapp_buffer('worker-proof',10,60)")
    claimed = cur.fetchall()
    assert [str(row["id"]) for row in claimed] == [str(outbound_id)]


def test_ledger_failure_rolls_back_inert_outbound_and_message(cur):
    data = transport_scenario(cur)
    turn, outbound_buffer, outbound_message = atomic_payload(data, expected_revision=9)
    cur.execute("savepoint before_failed_atomic_commit")
    with pytest.raises(Exception, match="ledger revision conflict"):
        cur.execute(
            "select public.commit_graph_turn_and_outbox_v3(%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)",
            (json.dumps(turn), json.dumps(outbound_buffer), json.dumps(outbound_message), json.dumps({"ok": True})),
        )
    cur.execute("rollback to savepoint before_failed_atomic_commit")
    cur.execute(
        "select count(*) count from public.lead_buffer where idempotency_key=%s",
        (outbound_buffer["idempotency_key"],),
    )
    assert cur.fetchone()["count"] == 0
    cur.execute(
        "select count(*) count from public.messages where channel_binding_id=%s and correlation_id=%s",
        (data["binding_id"], outbound_message["correlation_id"]),
    )
    assert cur.fetchone()["count"] == 0


def test_publication_payload_is_immutable(cur):
    _persona_id, _lead_ref, publication_id, _checksum, _chunk_id = scenario(cur)
    with pytest.raises(Exception, match="compiled graph publication content is immutable"):
        cur.execute(
            "update public.graph_publications set document_json='{\"changed\":true}' where id=%s",
            (publication_id,),
        )


def test_graph_json_publication_grant_reuses_protected_embed_without_opening_manual_edges(cur):
    persona_id = str(uuid.uuid4())
    graph_id = "graph:test:grant"
    cur.execute(
        "insert into public.personas(id,slug,name) values(%s,%s,'Grant')",
        (persona_id, f"grant-{persona_id[:8]}"),
    )
    cur.execute(
        """
        insert into public.knowledge_nodes(persona_id,node_type,slug,title,status,metadata)
        values(%s,'product','source','Source','validated',%s::jsonb) returning id
        """,
        (persona_id, json.dumps({"graph_json_id": graph_id, "graph_json_node_id": "source"})),
    )
    source_id = cur.fetchone()["id"]
    cur.execute(
        """
        insert into public.knowledge_nodes(persona_id,node_type,slug,title,status,metadata)
        values(%s,'embed','embedded','Embedded','active',%s::jsonb) returning id
        """,
        (persona_id, json.dumps({"graph_json_id": graph_id, "graph_json_node_id": "embedded"})),
    )
    embed_id = cur.fetchone()["id"]
    grant_metadata = {
        "active": True, "graph_json_id": graph_id,
        "graph_json_edge_id": "edge:source:embedded",
    }
    cur.execute(
        """
        insert into public.knowledge_edges(
          persona_id,source_node_id,target_node_id,relation_type,metadata
        ) values(%s,%s,%s,'publishes_to',%s::jsonb) returning id
        """,
        (persona_id, source_id, embed_id, json.dumps(grant_metadata)),
    )
    assert cur.fetchone()["id"]

    with pytest.raises(Exception, match="cannot connect directly to EMBED"):
        cur.execute(
            """
            insert into public.knowledge_edges(
              persona_id,source_node_id,target_node_id,relation_type,metadata
            ) values(%s,%s,%s,'visible_to_agent','{\"active\":true}'::jsonb)
            """,
            (persona_id, source_id, embed_id),
        )
