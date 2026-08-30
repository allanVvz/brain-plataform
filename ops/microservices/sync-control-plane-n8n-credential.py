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


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in {"--dry-run", "--audit-registry", "--apply"} or ROOT != Path("/opt/brain-ai"):
        raise SystemExit("invalid mode or production root")
    if mode == "--audit-registry":
        container = json.loads(subprocess.check_output(
            ["docker", "inspect", "brain-ai-n8n-1"], text=True
        ))[0]
        env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
        database_type = env.get("DB_TYPE", "sqlite")
        if database_type == "sqlite":
            user_folder = env.get("N8N_USER_FOLDER", "/home/node/.n8n")
            database_path = f"{user_folder.rstrip('/')}/database.sqlite"
            node = """const sqlite3=require('sqlite3').verbose();const db=new sqlite3.Database(process.argv[1],sqlite3.OPEN_READONLY);const q=\"SELECT m.name AS table_name,p.name AS column_name FROM sqlite_master m JOIN pragma_table_info(m.name) p WHERE m.type='table' AND (lower(p.name) LIKE '%apikey%' OR (lower(p.name) LIKE '%api%' AND lower(p.name) LIKE '%key%')) ORDER BY m.name,p.name\";db.all(q,(e,r)=>{if(e){console.error(e.message);process.exit(1)}console.log(JSON.stringify(r));db.close()});"""
            output = subprocess.check_output(
                ["docker", "exec", "brain-ai-n8n-1", "node", "-e", node, database_path],
                text=True,
            )
            rows = json.loads(output)
            columns = [f"{row['table_name']}.{row['column_name']}" for row in rows]
            print("N8N_API_KEY_REGISTRY_AUDIT database=sqlite columns=" + ",".join(columns))
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
