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
    cur.execute("select count(*) count from public.conversation_facts where ledger_id=%s and is_current", (first["ledger_id"],))
    assert cur.fetchone()["count"] == 1


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
