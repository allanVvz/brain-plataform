#!/usr/bin/env python3
"""Move one legacy n8n model credential into the existing persona secret store.

The plaintext exists only in process memory and is sent to the active control
plane over stdin.  It is never printed, placed in argv/environment, or written
to disk.  This is a one-time cutover utility; it creates no schema objects.
"""
from __future__ import annotations

import json
import os
import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("AUDIT_ROOT", "/opt/brain-ai")).resolve()
SLOTS = ROOT / ".deploy" / "microservices" / "slots.json"


def _json_from_output(value: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(value):
        if char not in "[{":
            continue
        try:
            document, _ = decoder.raw_decode(value[index:])
            return document
        except json.JSONDecodeError:
            continue
    raise RuntimeError("command did not return a JSON document")


def _run(args: list[str], *, stdin: str | None = None) -> str:
    completed = subprocess.run(
        args,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or ["command failed"]
        raise RuntimeError(detail[0][:500])
    return completed.stdout


def _control_container() -> str:
    state = json.loads(SLOTS.read_text(encoding="utf-8"))
    slot = str((state.get("control-plane") or {}).get("active") or "")
    if slot not in {"blue", "green"}:
        raise RuntimeError("active control-plane slot is unavailable")
    return f"brain-ai-control-plane-{slot}-1"


def _connection_plan(container: str, persona_slug: str) -> dict[str, Any]:
    code = """
import json,sys
from services import supabase_client
slug=sys.argv[1]
p=supabase_client.get_persona(slug) or {}
c=supabase_client.get_persona_integration_connection(str(p.get('id') or ''),'deepseek') or {}
cfg=c.get('config_json') or {}
print(json.dumps({
  'persona_id': str(p.get('id') or ''),
  'user_id': str(c.get('user_id') or ''),
  'credential_id': str(cfg.get('n8n_credential_id') or ''),
  'encrypted_secret': bool(c.get('secret_ciphertext')),
  'enabled': bool(c.get('enabled')),
  'model': str(cfg.get('model') or ''),
  'structured_output_mode': str(cfg.get('structured_output_mode') or ''),
}))
"""
    output = _run(["docker", "exec", container, "python", "-c", code, persona_slug])
    plan = _json_from_output(output)
    if not isinstance(plan, dict) or not plan.get("persona_id"):
        raise RuntimeError("persona integration is unavailable")
    if not plan.get("credential_id") and not plan.get("encrypted_secret"):
        raise RuntimeError("legacy credential reference is unavailable")
    return plan


def _export_credential(credential_id: str, *, decrypted: bool) -> dict[str, Any]:
    command = [
        "docker", "exec", "brain-ai-n8n-1", "n8n", "export:credentials",
        f"--id={credential_id}",
    ]
    if decrypted:
        command.append("--decrypted")
    document = _json_from_output(_run(command))
    rows = document if isinstance(document, list) else [document]
    row = next(
        (item for item in rows if isinstance(item, dict) and str(item.get("id")) == credential_id),
        None,
    )
    if not row or row.get("type") != "httpHeaderAuth":
        raise RuntimeError("legacy model credential is missing or has the wrong type")
    return row


def _api_key(row: dict[str, Any]) -> str:
    data = row.get("data") or {}
    if not isinstance(data, dict) or str(data.get("name") or "").lower() != "authorization":
        raise RuntimeError("legacy credential is not an Authorization header")
    value = str(data.get("value") or "").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value.startswith("sk-"):
        raise RuntimeError("legacy model credential has an invalid value")
    return value


def _store(container: str, persona_slug: str, api_key: str, model: str) -> dict[str, Any]:
    code = """
import hashlib,json,sys
from datetime import datetime,timezone
from services import integration_service,secret_store,supabase_client
payload=json.loads(sys.stdin.read())
slug=payload['persona_slug']; secret=payload['api_key']; model=payload['model']
p=supabase_client.get_persona(slug) or {}
c=supabase_client.get_persona_integration_connection(str(p.get('id') or ''),'deepseek') or {}
cfg=dict(c.get('config_json') or {})
integration_service.validate_deepseek(secret,model=model)
for key in ('n8n_credential_id','n8n_workflow_id','conversation_webhook_path','workflow_checksum','workflow_template'):
    cfg.pop(key,None)
cfg.update({
  'model':model,
  'pipeline_contract':'conversation_agentic_v1',
  'runtime_version':'graph_agent_runtime_v3',
  'structured_output_mode':str(cfg.get('structured_output_mode') or 'json_object'),
  'fingerprint':hashlib.sha256(secret.encode()).hexdigest()[:12],
})
supabase_client.save_persona_integration_connection({
  'persona_id':str(p['id']), 'user_id':str(c.get('user_id') or ''),
  'service':'deepseek', 'enabled':True, 'status':'connected',
  'config_json':cfg, 'secret_ciphertext':secret_store.encrypt_secret(secret),
  'last_validated_at':datetime.now(timezone.utc).isoformat(), 'last_error':None,
})
saved=supabase_client.get_persona_integration_connection(str(p['id']),'deepseek') or {}
verified=secret_store.decrypt_secret(saved.get('secret_ciphertext')) == secret
print(json.dumps({'verified':verified,'model':(saved.get('config_json') or {}).get('model'),'pipeline_contract':(saved.get('config_json') or {}).get('pipeline_contract'),'legacy_ids_removed':not any((saved.get('config_json') or {}).get(k) for k in ('n8n_credential_id','n8n_workflow_id'))}))
"""
    payload = json.dumps({"persona_slug": persona_slug, "api_key": api_key, "model": model})
    result = _json_from_output(
        _run(["docker", "exec", "-i", container, "python", "-c", code], stdin=payload)
    )
    if not isinstance(result, dict) or result.get("verified") is not True:
        raise RuntimeError("encrypted conversation model secret could not be verified")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--dry-run", dest="mode", action="store_const", const="--dry-run")
    mode_group.add_argument("--apply", dest="mode", action="store_const", const="--apply")
    parser.add_argument("persona_slug")
    parser.add_argument("--model", help="provider model id to validate and persist")
    args = parser.parse_args()
    mode, persona_slug = args.mode, args.persona_slug
    if ROOT != Path("/opt/brain-ai") or not persona_slug.replace("-", "").isalnum():
        raise SystemExit("invalid production root or persona slug")
    container = _control_container()
    plan = _connection_plan(container, persona_slug)
    model = str(args.model or plan["model"] or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", model):
        raise SystemExit("invalid conversation model id")
    if plan["encrypted_secret"]:
        print("CONVERSATION_MODEL_SECRET already_migrated=true")
        return 0
    _export_credential(str(plan["credential_id"]), decrypted=False)
    print(
        "CONVERSATION_MODEL_SECRET_PLAN "
        f"persona={persona_slug} enabled={str(plan['enabled']).lower()} "
        f"model={model} "
        f"structured_output_mode={plan['structured_output_mode'] or 'missing'}"
    )
    if mode == "--dry-run":
        return 0
    if os.environ.get("CONVERSATION_SECRET_MIGRATION_AUTHORIZED") != "true":
        raise SystemExit("authorization marker missing")
    secret = _api_key(_export_credential(str(plan["credential_id"]), decrypted=True))
    result = _store(container, persona_slug, secret, model)
    print(
        "CONVERSATION_MODEL_SECRET_RESULT migrated=true verified=true "
        f"model={result['model']} "
        f"pipeline_contract={result['pipeline_contract']} "
        f"legacy_ids_removed={str(result['legacy_ids_removed']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
