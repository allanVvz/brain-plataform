#!/usr/bin/env bash
# Run only on a disposable, backup-restored database after applying migration 163.
# Requires VPS docker compose, host python3, and psql in the database container.
set -Eeuo pipefail
restore_db="${1:?Pass the isolated restore database name}"
[[ "$restore_db" =~ ^brain_restore_schema163_[0-9]{14}$ ]] || { echo 'Refusing non-isolated database'; exit 2; }
COMPOSE=(docker compose --env-file .env.compose -f docker-compose.yml -f infra/microservices/docker-compose.blue-green.yml)
psql_db() { "${COMPOSE[@]}" exec -T db sh -c 'exec psql -X -U "$POSTGRES_USER" -d "$1" -Atq -v ON_ERROR_STOP=1' sh "$restore_db"; }
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
# Exercise the actual CP RPC transport contract against an untouched baseline.
psql_db <<'SQL' > "$work_dir/canonical-active.json"
SET ROLE brain_control_plane;
SELECT public.read_graph_editor_publication_v1(persona_id) FROM public.graph_publications
WHERE status='active' AND document_json->>'faq_projection_contract'='v1' ORDER BY version DESC LIMIT 1;
SQL
python3 - "$work_dir/canonical-active.json" <<'PYCODE'
import hashlib, json, sys
payload=json.load(open(sys.argv[1]))
assert isinstance(payload["document_text"],str)
doc=json.loads(payload["document_text"])
checksum=doc.pop("checksum")
actual="sha256:"+hashlib.sha256(json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
assert actual==checksum==payload["publication"]["checksum"], "canonical active RPC checksum mismatch"
PYCODE
# This helper is temporary to each restore-only psql connection. PostgreSQL
# generated/identity columns are recomputed instead of copied into INSERT.
clone_sql=$(cat <<'SQL'
CREATE FUNCTION pg_temp.insert_graph_editor_records(p_table regclass,p_records jsonb)
RETURNS bigint LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE v_columns text; v_count bigint;
BEGIN
 SELECT string_agg(quote_ident(attname),', ' ORDER BY attnum) INTO v_columns
 FROM pg_attribute WHERE attrelid=p_table AND attnum>0 AND NOT attisdropped
   AND attgenerated='' AND attidentity='';
 IF v_columns IS NULL THEN RAISE EXCEPTION 'Clone table has no writable columns'; END IF;
 EXECUTE format('INSERT INTO %s (%s) SELECT %s FROM jsonb_populate_recordset(NULL::%s,$1)',
   p_table,v_columns,v_columns,p_table) USING p_records;
 GET DIAGNOSTICS v_count=ROW_COUNT;
 RETURN v_count;
END $$;
SQL
)
# Clone a restored active snapshot into an isolated candidate, including its
# existing ready projections. Fixtures exist only in this disposable restore.
psql_db <<SQL > "$work_dir/fixture"
$clone_sql
CREATE TEMP TABLE clone_generated_fixture (
 id bigint GENERATED ALWAYS AS IDENTITY,
 payload jsonb NOT NULL,
 search_document text GENERATED ALWAYS AS (payload->>'text') STORED
);
SELECT pg_temp.insert_graph_editor_records('pg_temp.clone_generated_fixture',
 '[{"id":999,"payload":{"text":"generated-proof"},"search_document":"must-not-copy"}]') AS fixture_cloned \gset
SELECT count(*)=1 AND bool_and(id<>999 AND search_document='generated-proof') AS generated_clone_valid FROM clone_generated_fixture \gset
\if :generated_clone_valid
\else
\quit 1
\endif
SELECT id AS base_id,persona_id FROM public.graph_publications
WHERE status='active' AND document_json->>'faq_projection_contract'='v1' ORDER BY version DESC LIMIT 1 \gset
SELECT gen_random_uuid() AS candidate_id \gset
INSERT INTO public.graph_publications(id,persona_id,version,checksum,document_json,status,compiler_version,editor_lease_token,editor_lease_until)
SELECT :'candidate_id',persona_id,(SELECT max(version)+1 FROM public.graph_publications WHERE persona_id=:'persona_id'),
 'sha256:'||encode(digest(:'candidate_id','sha256'),'hex'),
 jsonb_set(document_json,'{checksum}',to_jsonb('sha256:'||encode(digest(:'candidate_id','sha256'),'hex'))),
 'building',compiler_version,:'candidate_id'::uuid,now()+interval '15 minutes' FROM public.graph_publications WHERE id=:'base_id';
SELECT pg_temp.insert_graph_editor_records('public.graph_node_coordinates',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('publication_id',:'candidate_id','editor_lease_token',:'candidate_id')),'[]'::jsonb)) AS cloned
 FROM public.graph_node_coordinates t WHERE publication_id=:'base_id' \gset
SELECT pg_temp.insert_graph_editor_records('public.graph_branch_memberships',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('publication_id',:'candidate_id','editor_lease_token',:'candidate_id')),'[]'::jsonb)) AS cloned
 FROM public.graph_branch_memberships t WHERE publication_id=:'base_id' \gset
SELECT pg_temp.insert_graph_editor_records('public.graph_branch_contracts',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('publication_id',:'candidate_id','editor_lease_token',:'candidate_id')),'[]'::jsonb)) AS cloned
 FROM public.graph_branch_contracts t WHERE publication_id=:'base_id' \gset
CREATE TEMP TABLE entry_map AS SELECT id AS old_id,gen_random_uuid() AS new_id FROM public.knowledge_rag_entries WHERE publication_id=:'base_id';
SELECT pg_temp.insert_graph_editor_records('public.knowledge_rag_entries',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('id',m.new_id,'publication_id',:'candidate_id',
 'canonical_key','rehearsal:'||m.new_id,'metadata',(t.metadata-'editor_lease_token')||jsonb_build_object('editor_lease_token',:'candidate_id'),'graph_checksum','sha256:'||encode(digest(:'candidate_id','sha256'),'hex'))),'[]'::jsonb)) AS cloned
 FROM public.knowledge_rag_entries t JOIN entry_map m ON m.old_id=t.id \gset
SELECT pg_temp.insert_graph_editor_records('public.knowledge_rag_chunks',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('id',gen_random_uuid(),'publication_id',:'candidate_id','rag_entry_id',m.new_id,
 'metadata',(t.metadata-'editor_lease_token')||jsonb_build_object('editor_lease_token',:'candidate_id'),'graph_checksum','sha256:'||encode(digest(:'candidate_id','sha256'),'hex'))),'[]'::jsonb)) AS cloned
 FROM public.knowledge_rag_chunks t JOIN entry_map m ON m.old_id=t.rag_entry_id \gset
SELECT public.finish_graph_publication_build_v1(:'candidate_id',:'candidate_id',false) AS built \gset
UPDATE public.knowledge_nodes SET metadata=metadata||'{"graph_position":{"x":10,"y":20}}'::jsonb
WHERE id=(SELECT (n->>'projection_node_id')::uuid FROM public.graph_publications p,LATERAL jsonb_array_elements(p.document_json->'nodes') n WHERE p.id=:'base_id' LIMIT 1);
SELECT :'persona_id'||'|'||:'base_id'||'|'||:'candidate_id'||'|sha256:'||encode(digest(:'candidate_id','sha256'),'hex');
SQL
IFS='|' read -r persona_id base_id candidate_id checksum < "$work_dir/fixture"
[[ "$persona_id" =~ ^[a-f0-9-]{36}$ && "$base_id" =~ ^[a-f0-9-]{36}$ && "$candidate_id" =~ ^[a-f0-9-]{36}$ ]] || { echo 'Invalid rehearsal fixture'; exit 1; }
request_hash="sha256:$(printf 'rehearsal' | sha256sum | cut -d' ' -f1)"
# Two independent psql connections must have exactly one CAS winner.
for sequence in 1 2; do
  (psql_db <<SQL
SET ROLE brain_control_plane;
SELECT pg_sleep(0.2);
SELECT public.commit_graph_editor_v1('$persona_id','$candidate_id','$base_id','schema-rehearsal','race-$sequence','$request_hash','publish','$checksum','{}');
SQL
  ) > "$work_dir/race-$sequence.log" 2>&1 &
  if [[ "$sequence" == 1 ]]; then pid_1=$!; else pid_2=$!; fi
done
successes=0
wait "$pid_1" && successes=$((successes+1)) || true
wait "$pid_2" && successes=$((successes+1)) || true
[[ "$successes" == 1 ]] || { echo 'CAS must have exactly one winner'; cat "$work_dir"/race-*.log; exit 1; }
psql_db <<SQL
$clone_sql
SET ROLE brain_control_plane;
DO \$proof\$
DECLARE v_result jsonb; v_key text; v_document jsonb; v_first jsonb; v_second jsonb; v_coordinate jsonb; v_node_id uuid; v_unpublished uuid; v_edge public.knowledge_edges%ROWTYPE;
BEGIN
 SELECT payload->>'idempotency_key' INTO v_key FROM public.system_events
 WHERE persona_id='$persona_id' AND event_type='graph_editor_committed' AND payload->>'actor'='schema-rehearsal';
 v_result:=public.graph_editor_receipt_v1('$persona_id','schema-rehearsal',v_key,'publish','$base_id','$request_hash');
 IF v_result->>'publication_id' <> '$candidate_id' THEN RAISE EXCEPTION 'receipt replay mismatch'; END IF;
 BEGIN
  PERFORM public.graph_editor_receipt_v1('$persona_id','different-actor',v_key,'publish','$base_id','$request_hash');
  RAISE EXCEPTION 'receipt allowed another actor';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 BEGIN
  PERFORM public.graph_editor_receipt_v1('$persona_id','schema-rehearsal',v_key,'publish','$base_id','sha256:'||repeat('0',64));
  RAISE EXCEPTION 'receipt accepted different payload';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 IF public.graph_editor_previous_v1('$persona_id','$candidate_id')->>'id' <> '$base_id' THEN RAISE EXCEPTION 'activation lineage missing'; END IF;
 v_result:=public.commit_graph_editor_v1('$persona_id','$base_id','$candidate_id','schema-rehearsal','revert-1','$request_hash','revert',(SELECT checksum FROM public.graph_publications WHERE id='$base_id'),'{}');
 IF v_result->>'publication_id' <> '$base_id' THEN RAISE EXCEPTION 'revert failed'; END IF;
 v_result:=public.graph_editor_receipt_v1('$persona_id','schema-rehearsal',v_key,'publish','$base_id','$request_hash');
 IF v_result->>'publication_id' <> '$candidate_id' THEN RAISE EXCEPTION 'receipt not durable after revert'; END IF;
 v_document:=(SELECT document_json FROM public.graph_publications WHERE id='$base_id');
 v_document:=jsonb_set(v_document,'{checksum}',to_jsonb('sha256:'||encode(digest(gen_random_uuid()::text,'sha256'),'hex')));
 v_first:=public.reserve_graph_publication_v1('$persona_id',v_document);
 BEGIN
  PERFORM public.reserve_graph_publication_v1('$persona_id',v_document);
  RAISE EXCEPTION 'concurrent build was not fenced';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 UPDATE public.graph_publications SET editor_lease_until=now()-interval '1 second' WHERE id=(v_first->'publication'->>'id')::uuid;
 v_second:=public.reserve_graph_publication_v1('$persona_id',v_document);
 IF v_first->>'lease_token'=v_second->>'lease_token' THEN RAISE EXCEPTION 'expired lease not replaced'; END IF;
 SELECT to_jsonb(c) INTO v_coordinate FROM public.graph_node_coordinates c WHERE publication_id='$base_id' LIMIT 1;
 BEGIN
  PERFORM pg_temp.insert_graph_editor_records('public.graph_node_coordinates',jsonb_build_array(
   v_coordinate||jsonb_build_object('publication_id',v_second->'publication'->>'id','editor_lease_token',NULL)));
  RAISE EXCEPTION 'unleased projection write accepted';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 BEGIN
  PERFORM pg_temp.insert_graph_editor_records('public.graph_node_coordinates',jsonb_build_array(
   v_coordinate||jsonb_build_object('publication_id',v_second->'publication'->>'id','editor_lease_token',v_first->>'lease_token')));
  RAISE EXCEPTION 'stale projection write accepted';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 PERFORM pg_temp.insert_graph_editor_records('public.graph_node_coordinates',jsonb_build_array(
   v_coordinate||jsonb_build_object('publication_id',v_second->'publication'->>'id','editor_lease_token',v_second->>'lease_token')));
 PERFORM public.finish_graph_publication_build_v1((v_second->'publication'->>'id')::uuid,(v_second->>'lease_token')::uuid,true);
 IF (SELECT id FROM public.graph_publications WHERE persona_id='$persona_id' AND status='active') <> '$base_id' THEN RAISE EXCEPTION 'recovery changed active publication'; END IF;
 SELECT (n->>'projection_node_id')::uuid INTO v_node_id FROM jsonb_array_elements(v_document->'nodes') n LIMIT 1;
 IF (SELECT metadata->'graph_position' FROM public.knowledge_nodes WHERE id=v_node_id) IS DISTINCT FROM '{"x":10,"y":20}'::jsonb THEN RAISE EXCEPTION 'visual position lost during CAS/revert'; END IF;
 BEGIN
  UPDATE public.knowledge_nodes SET title=title||' forbidden' WHERE id=v_node_id;
  RAISE EXCEPTION 'raw published content update accepted';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 UPDATE public.knowledge_nodes SET metadata=metadata||'{"graph_position":{"x":10,"y":20}}'::jsonb WHERE id=v_node_id;
 BEGIN
  UPDATE public.knowledge_nodes SET metadata=metadata||'{"required":true}'::jsonb WHERE id=v_node_id;
  RAISE EXCEPTION 'raw semantic metadata update accepted';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 SELECT * INTO v_edge FROM public.knowledge_edges WHERE persona_id='$persona_id' AND source_node_id IN
  (SELECT (n->>'projection_node_id')::uuid FROM jsonb_array_elements(v_document->'nodes') n)
 AND target_node_id IN (SELECT (n->>'projection_node_id')::uuid FROM jsonb_array_elements(v_document->'nodes') n) LIMIT 1;
 BEGIN
  UPDATE public.knowledge_edges SET weight=weight+1 WHERE id=v_edge.id;
  RAISE EXCEPTION 'raw published topology update accepted';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 v_unpublished:=gen_random_uuid();
 INSERT INTO public.knowledge_nodes(id,persona_id,node_type,slug,title,status) VALUES
 (v_unpublished,'$persona_id','asset','restore-asset-'||v_unpublished,'Restore-only asset','pending_validation');
 INSERT INTO public.knowledge_edges(persona_id,source_node_id,target_node_id,relation_type)
 VALUES ('$persona_id',v_node_id,v_unpublished,'uses_asset');
 IF has_function_privilege('brain_control_plane','public.activate_graph_publication_v3(uuid)','EXECUTE') THEN RAISE EXCEPTION 'direct activation privilege survived'; END IF;
 IF NOT has_function_privilege('brain_control_plane','public.commit_graph_editor_v1(uuid,uuid,uuid,text,text,text,text,text,jsonb)','EXECUTE') THEN RAISE EXCEPTION 'CAS writer grant missing'; END IF;
END \$proof\$;
SQL

# A separate raw writer cannot cross an in-flight persona publication lock.
(psql_db <<SQL
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('$persona_id'));
SELECT pg_sleep(4);
ROLLBACK;
SQL
) > "$work_dir/raw-lock.log" 2>&1 &
raw_holder=$!
lock_observed=false
for attempt in $(seq 1 30); do
  if [[ "$(psql_db <<< "SELECT pg_try_advisory_xact_lock(hashtext('$persona_id'));")" == f ]]; then lock_observed=true; break; fi
  sleep 0.1
done
[[ "$lock_observed" == true ]] || { wait "$raw_holder"; echo 'Raw race lock was not observed'; exit 1; }
if psql_db <<SQL > "$work_dir/raw-race.log" 2>&1
SET ROLE brain_control_plane;
UPDATE public.knowledge_nodes SET metadata=metadata||'{"graph_position":{"x":30,"y":40}}'::jsonb
WHERE id=(SELECT (n->>'projection_node_id')::uuid FROM public.graph_publications p,LATERAL jsonb_array_elements(p.document_json->'nodes') n WHERE p.id='$base_id' LIMIT 1);
SQL
then echo 'Raw writer crossed publication lock'; wait "$raw_holder"; exit 1; fi
grep -q 'raw_published_graph_write_requires_editor' "$work_dir/raw-race.log" || { cat "$work_dir/raw-race.log"; wait "$raw_holder"; exit 1; }
wait "$raw_holder"

# NULL bootstrap is exercised against a new persona only in the restored DB.
psql_db <<SQL
$clone_sql
SELECT '$base_id' AS base_id,gen_random_uuid() AS bootstrap_persona \gset
INSERT INTO public.personas(id,slug,name) VALUES (:'bootstrap_persona','schema-rehearsal-'||:'bootstrap_persona','Disposable schema rehearsal');
CREATE TEMP TABLE bootstrap_node_map AS SELECT (n->>'projection_node_id')::uuid AS old_id,gen_random_uuid() AS new_id
FROM public.graph_publications p,LATERAL jsonb_array_elements(p.document_json->'nodes') n WHERE p.id=:'base_id';
CREATE TEMP TABLE bootstrap_doc AS SELECT jsonb_set(jsonb_set(document_json,'{persona,id}',to_jsonb(:'bootstrap_persona'::text)),
 '{checksum}',to_jsonb('sha256:'||encode(digest(:'bootstrap_persona','sha256'),'hex'))) AS doc FROM public.graph_publications WHERE id=:'base_id';
UPDATE bootstrap_doc SET doc=jsonb_set(doc,'{nodes}',(SELECT jsonb_agg(jsonb_set(n,'{projection_node_id}',to_jsonb(m.new_id::text)))
 FROM jsonb_array_elements(doc->'nodes') n JOIN bootstrap_node_map m ON m.old_id=(n->>'projection_node_id')::uuid));
UPDATE bootstrap_doc SET doc=jsonb_set(doc,'{node_by_id}',(SELECT jsonb_object_agg(n->>'id',n) FROM jsonb_array_elements(doc->'nodes') n));
SELECT public.reserve_graph_publication_v1(:'bootstrap_persona',doc) AS reservation FROM bootstrap_doc \gset
SELECT :'reservation'::jsonb->'publication'->>'id' AS bootstrap_id,:'reservation'::jsonb->>'lease_token' AS bootstrap_token \gset
SELECT pg_temp.insert_graph_editor_records('public.graph_node_coordinates',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('publication_id',:'bootstrap_id','editor_lease_token',:'bootstrap_token')),'[]'::jsonb)) AS cloned
 FROM public.graph_node_coordinates t WHERE publication_id=:'base_id' \gset
SELECT pg_temp.insert_graph_editor_records('public.graph_branch_memberships',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('publication_id',:'bootstrap_id','editor_lease_token',:'bootstrap_token')),'[]'::jsonb)) AS cloned
 FROM public.graph_branch_memberships t WHERE publication_id=:'base_id' \gset
SELECT pg_temp.insert_graph_editor_records('public.graph_branch_contracts',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('publication_id',:'bootstrap_id','editor_lease_token',:'bootstrap_token')),'[]'::jsonb)) AS cloned
 FROM public.graph_branch_contracts t WHERE publication_id=:'base_id' \gset
CREATE TEMP TABLE bootstrap_entry_map AS SELECT id AS old_id,gen_random_uuid() AS new_id FROM public.knowledge_rag_entries WHERE publication_id=:'base_id';
SELECT pg_temp.insert_graph_editor_records('public.knowledge_rag_entries',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('persona_id',:'bootstrap_persona','source_node_id',(SELECT new_id FROM bootstrap_node_map WHERE old_id=t.source_node_id),'id',m.new_id,'publication_id',:'bootstrap_id',
 'canonical_key','rehearsal:'||m.new_id,'metadata',(t.metadata-'editor_lease_token')||jsonb_build_object('editor_lease_token',:'bootstrap_token'),'graph_checksum','sha256:'||encode(digest(:'bootstrap_persona','sha256'),'hex'))),'[]'::jsonb)) AS cloned
 FROM public.knowledge_rag_entries t JOIN bootstrap_entry_map m ON m.old_id=t.id \gset
SELECT pg_temp.insert_graph_editor_records('public.knowledge_rag_chunks',coalesce(jsonb_agg(
 to_jsonb(t)||jsonb_build_object('persona_id',:'bootstrap_persona','source_node_id',(SELECT new_id FROM bootstrap_node_map WHERE old_id=t.source_node_id),'id',gen_random_uuid(),'publication_id',:'bootstrap_id','rag_entry_id',m.new_id,
 'metadata',(t.metadata-'editor_lease_token')||jsonb_build_object('editor_lease_token',:'bootstrap_token'),'graph_checksum','sha256:'||encode(digest(:'bootstrap_persona','sha256'),'hex'))),'[]'::jsonb)) AS cloned
 FROM public.knowledge_rag_chunks t JOIN bootstrap_entry_map m ON m.old_id=t.rag_entry_id \gset

SELECT public.finish_graph_publication_build_v1(:'bootstrap_id',:'bootstrap_token',false) AS built \gset
SELECT :'bootstrap_persona' AS bootstrap_persona,:'bootstrap_id' AS bootstrap_id,
 'sha256:'||encode(digest(:'bootstrap_persona','sha256'),'hex') AS bootstrap_checksum \gset
SET ROLE brain_control_plane;
SELECT public.commit_graph_editor_v1(:'bootstrap_persona',:'bootstrap_id',NULL,'schema-rehearsal','bootstrap-null','$request_hash','publish',:'bootstrap_checksum','{}') AS bootstrap_result \gset
SELECT public.graph_editor_receipt_v1(:'bootstrap_persona','schema-rehearsal','bootstrap-null','publish',NULL,'$request_hash') = :'bootstrap_result'::jsonb AS bootstrap_replay \gset
\if :bootstrap_replay
\else
\quit 1
\endif
-- A different NULL-base publication on an already active persona must conflict.
SELECT set_config('rehearsal.bootstrap_persona',:'bootstrap_persona',false),set_config('rehearsal.bootstrap_id',:'bootstrap_id',false);
DO \$proof\$ BEGIN
 BEGIN
  PERFORM public.commit_graph_editor_v1(current_setting('rehearsal.bootstrap_persona')::uuid,current_setting('rehearsal.bootstrap_id')::uuid,NULL,
   'schema-rehearsal','bootstrap-second','$request_hash','publish','sha256:'||repeat('0',64),'{}');
  RAISE EXCEPTION 'bootstrap NULL accepted over active';
 EXCEPTION WHEN serialization_failure THEN NULL; END;
 BEGIN
  PERFORM public.graph_editor_receipt_v1(current_setting('rehearsal.bootstrap_persona')::uuid,'schema-rehearsal','save-null','save',NULL,'$request_hash');
  RAISE EXCEPTION 'save NULL accepted';
 EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
END \$proof\$;
SQL

echo 'GRAPH_EDITOR_SCHEMA_REHEARSAL=passed (isolated snapshot, two connections, durable receipt, lineage, lease recovery, stale-worker/source fencing, NULL bootstrap, payload mismatch, grants)'
