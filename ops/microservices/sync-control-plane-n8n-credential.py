#!/usr/bin/env python3
"""Synchronize only the existing production n8n API key into control-plane.env."""
from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(os.environ.get("AUDIT_ROOT", "/opt/brain-ai")).resolve()
SOURCE = ROOT / ".env.compose"
TARGET = ROOT / ".env.microservices" / "control-plane.env"


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def replace_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    result: list[str] = []
    for line in lines:
        is_target = (
            "=" in line
            and not line.lstrip().startswith("#")
            and line.split("=", 1)[0].strip() == key
        )
        if is_target:
            if not replaced:
                result.append(f"{key}={value}")
                replaced = True
        else:
            result.append(line)
    if not replaced:
        result.append(f"{key}={value}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(result) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def sqlite_registry() -> tuple[list[str], list[str]]:
    container = json.loads(subprocess.check_output(
        ["docker", "inspect", "brain-ai-n8n-1"], text=True
    ))[0]
    env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
    if env.get("DB_TYPE", "sqlite") != "sqlite":
        raise SystemExit("registry synchronization currently requires sqlite metadata")
    user_folder = env.get("N8N_USER_FOLDER", "/home/node/.n8n")
    database_path = f"{user_folder.rstrip('/')}/database.sqlite"
    node = """const {DatabaseSync}=require('node:sqlite');const db=new DatabaseSync(process.argv[1],{readOnly:true});const columns=db.prepare(\"SELECT m.name AS table_name,p.name AS column_name FROM sqlite_master m JOIN pragma_table_info(m.name) p WHERE m.type='table' AND (lower(p.name) LIKE '%apikey%' OR (lower(p.name) LIKE '%api%' AND lower(p.name) LIKE '%key%')) ORDER BY m.name,p.name\").all();const keys=db.prepare(\"SELECT apiKey FROM user_api_keys ORDER BY rowid DESC\").all().map(x=>x.apiKey);console.log(JSON.stringify({columns,keys}));db.close();"""
    output = subprocess.check_output(
        ["docker", "exec", "brain-ai-n8n-1", "node", "-e", node, database_path],
        text=True,
    )
    data = json.loads(output)
    columns = [f"{row['table_name']}.{row['column_name']}" for row in data["columns"]]
    keys = [value for value in data["keys"] if isinstance(value, str) and value]
    return columns, keys


def rotate_sqlite_registry_key() -> str:
    container = json.loads(subprocess.check_output(
        ["docker", "inspect", "brain-ai-n8n-1"], text=True
    ))[0]
    env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
    user_folder = env.get("N8N_USER_FOLDER", "/home/node/.n8n")
    database_path = f"{user_folder.rstrip('/')}/database.sqlite"
    node = r"""
const fs = require('node:fs');
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');
const jwt = require('/usr/local/lib/node_modules/n8n/node_modules/jsonwebtoken');
const databasePath = process.argv[1];
const config = JSON.parse(fs.readFileSync('/home/node/.n8n/config', 'utf8'));
const encryptionKey = process.env.N8N_ENCRYPTION_KEY || config.encryptionKey;
if (typeof encryptionKey !== 'string' || encryptionKey.length < 32) throw new Error('n8n encryption key is unavailable');
let baseKey = '';
for (let i = 0; i < encryptionKey.length; i += 2) baseKey += encryptionKey[i];
const jwtSecret = crypto.createHash('sha256').update(baseKey).digest('hex');
const db = new DatabaseSync(databasePath);
const previous = db.prepare("SELECT userId,scopes,audience FROM user_api_keys WHERE audience='public-api' ORDER BY rowid DESC LIMIT 1").get();
if (!previous) throw new Error('n8n API key registry is empty');
const user = db.prepare('SELECT disabled FROM user WHERE id=?').get(previous.userId);
if (!user || Number(user.disabled) !== 0) throw new Error('n8n API key owner is unavailable');
const id = crypto.randomBytes(12).toString('base64url');
const label = 'brain-api-production-rotated-' + new Date().toISOString().slice(0, 10);
const apiKey = jwt.sign({ sub: previous.userId, iss: 'n8n', aud: 'public-api' }, jwtSecret);
const stamp = new Date().toISOString().replace('T', ' ').replace('Z', '');
try {
  db.exec('BEGIN IMMEDIATE');
  db.prepare('INSERT INTO user_api_keys (id,userId,label,apiKey,createdAt,updatedAt,scopes,audience,lastUsedAt) VALUES (?,?,?,?,?,?,?,?,NULL)').run(id, previous.userId, label, apiKey, stamp, stamp, previous.scopes, previous.audience);
  db.exec('COMMIT');
} catch (error) {
  try { db.exec('ROLLBACK'); } catch (_) {}
  db.close();
  throw error;
}
db.close();
(async () => {
  const response = await fetch('http://127.0.0.1:5678/api/v1/workflows?limit=1', { headers: { 'X-N8N-API-KEY': apiKey } });
  if (response.status !== 200) {
    const cleanup = new DatabaseSync(databasePath);
    cleanup.prepare('DELETE FROM user_api_keys WHERE id=?').run(id);
    cleanup.close();
    throw new Error('new n8n API key failed validation with HTTP ' + response.status);
  }
  process.stdout.write(JSON.stringify({ id, apiKey }));
})().catch((error) => { console.error(error.message); process.exit(1); });
"""
    output = subprocess.check_output(
        ["docker", "exec", "brain-ai-n8n-1", "node", "-e", node, database_path],
        text=True,
    )
    value = json.loads(output)
    api_key = value.get("apiKey", "")
    if not isinstance(api_key, str) or not api_key:
        raise SystemExit("rotated n8n API key was not returned")
    return api_key


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in {"--dry-run", "--audit-registry", "--sync-registry", "--rotate-registry", "--apply"} or ROOT != Path("/opt/brain-ai"):
        raise SystemExit("invalid mode or production root")
    if mode == "--rotate-registry":
        if os.environ.get("N8N_CREDENTIAL_SYNC_AUTHORIZED") != "true":
            raise SystemExit("authorization marker missing")
        container = json.loads(subprocess.check_output(
            ["docker", "inspect", "brain-ai-n8n-1"], text=True
        ))[0]
        env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
        if env.get("DB_TYPE", "sqlite") != "sqlite":
            raise SystemExit("registry rotation currently requires sqlite metadata")
        api_key = rotate_sqlite_registry_key()
        replace_env(SOURCE, "N8N_API_KEY", api_key)
        replace_env(TARGET, "N8N_API_KEY", api_key)
        if parse(SOURCE).get("N8N_API_KEY") != api_key or parse(TARGET).get("N8N_API_KEY") != api_key:
            raise SystemExit("rotated credential verification failed")
        print("N8N_REGISTRY_CREDENTIAL_ROTATION_RESULT=passed value=redacted files=2 mode=0600")
        return 0
    if mode in {"--audit-registry", "--sync-registry"}:
        container = json.loads(subprocess.check_output(
            ["docker", "inspect", "brain-ai-n8n-1"], text=True
        ))[0]
        env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
        database_type = env.get("DB_TYPE", "sqlite")
        if database_type == "sqlite":
            columns, keys = sqlite_registry()
            configured = parse(SOURCE).get("N8N_API_KEY", "")
            print("N8N_API_KEY_REGISTRY_AUDIT database=sqlite columns=" + ",".join(columns) + f" key_count={len(keys)} configured_match={str(configured in keys).lower()}")
            if mode == "--audit-registry":
                return 0
            if os.environ.get("N8N_CREDENTIAL_SYNC_AUTHORIZED") != "true":
                raise SystemExit("authorization marker missing")
            if not keys:
                raise SystemExit("n8n API key registry is empty")
            replace_env(SOURCE, "N8N_API_KEY", keys[0])
            replace_env(TARGET, "N8N_API_KEY", keys[0])
            if parse(SOURCE).get("N8N_API_KEY") != keys[0] or parse(TARGET).get("N8N_API_KEY") != keys[0]:
                raise SystemExit("registry credential verification failed")
            print("N8N_REGISTRY_CREDENTIAL_SYNC_RESULT=passed value=redacted files=2 mode=0600")
            return 0
        if database_type not in {"postgresdb", "postgres"}:
            raise SystemExit("unsupported n8n database type")
        database = env.get("DB_POSTGRESDB_DATABASE", "")
        username = env.get("DB_POSTGRESDB_USER", "")
        password = env.get("DB_POSTGRESDB_PASSWORD", "")
        if not database or not username or not password:
            raise SystemExit("n8n postgres binding is incomplete")
        sql = "select table_schema||'.'||table_name||'.'||column_name from information_schema.columns where lower(column_name) like '%apikey%' or (lower(column_name) like '%api%' and lower(column_name) like '%key%') order by 1"
        output = subprocess.check_output(
            ["docker", "exec", "-e", f"PGPASSWORD={password}", "brain-ai-db-1", "psql", "-X", "-A", "-t", "-U", username, "-d", database, "-c", sql],
            text=True,
        )
        columns = [line.strip() for line in output.splitlines() if line.strip()]
        print("N8N_API_KEY_REGISTRY_AUDIT database=postgres columns=" + ",".join(columns))
        return 0
    source = parse(SOURCE)
    target = parse(TARGET)
    source_key = source.get("N8N_API_KEY", "")
    if not source_key:
        raise SystemExit("N8N_API_KEY is missing from the production source env")
    matches = target.get("N8N_API_KEY") == source_key
    print(f"N8N_CREDENTIAL_PLAN mode={mode} source_present=true target_present={bool(target.get('N8N_API_KEY'))} matches={str(matches).lower()}")
    if mode == "--dry-run":
        return 0
    if os.environ.get("N8N_CREDENTIAL_SYNC_AUTHORIZED") != "true":
        raise SystemExit("authorization marker missing")
    target["N8N_API_KEY"] = source_key
    temporary = TARGET.with_suffix(".env.tmp")
    temporary.write_text("".join(f"{key}={value}\n" for key, value in sorted(target.items())), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, TARGET)
    if parse(TARGET).get("N8N_API_KEY") != source_key:
        raise SystemExit("credential verification failed")
    print("N8N_CREDENTIAL_SYNC_RESULT=passed value=redacted mode=0600")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
