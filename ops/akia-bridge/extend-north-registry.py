#!/usr/bin/env python3
"""Generate/review an additive North registry extension; never run on import."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID


def checked_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('UUID must be a string')
    return str(UUID(value))


def validate_manifest(data: dict) -> dict:
    if not isinstance(data, dict) or data.get('approved') is not True:
        raise ValueError('Explicit approved manifest required')
    reference = data.get('approval_reference')
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 2000:
        raise ValueError('Approval reference required (maximum 2000 characters)')
    admin = checked_uuid(data.get('admin_app_user_id'))
    groups: dict[str, list[str]] = {}
    for key, agency in [('clients', 'north'), ('excluded', 'south')]:
        rows = data.get(key)
        if not isinstance(rows, list) or (key == 'clients' and not rows):
            raise ValueError(f'{key} must be an explicit list')
        ids = []
        for row in rows:
            if not isinstance(row, dict) or row.get('agency_slug') != agency:
                raise ValueError(f'{key} must classify every UUID as {agency}')
            ids.append(checked_uuid(row.get('north_client_id')))
        if len(ids) != len(set(ids)):
            raise ValueError(f'Duplicate UUID in {key}')
        groups[key] = sorted(ids)
    if set(groups['clients']) & set(groups['excluded']):
        raise ValueError('Included and excluded clients overlap')
    return {'admin': admin, 'clients': groups['clients'], 'excluded': groups['excluded'],
            'approval_reference': reference}


def sql_array(ids: list[str]) -> str:
    return 'ARRAY[' + ','.join("'" + checked_uuid(item) + "'::uuid" for item in ids) + ']::uuid[]'


def build_sql(data: dict) -> str:
    manifest = validate_manifest(data)
    clients, excluded = sql_array(manifest['clients']), sql_array(manifest['excluded'])
    admin = manifest['admin']
    # Only parsed UUIDs enter SQL. Approval prose never becomes executable text.
    return f"""-- Additive North registry extension; no business tables or identity writes.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
LOCK TABLE operations.north_client_registry IN SHARE ROW EXCLUSIVE MODE;
DO $guard$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.app_users u
    JOIN operations.platform_admins a ON a.app_user_id=u.id
    JOIN operations.north_identity_links i ON i.app_user_id=u.id AND i.enabled
    WHERE u.id='{admin}'::uuid AND u.is_active AND u.role='admin' AND u.account_type='internal'
  ) THEN RAISE EXCEPTION 'Approved existing Brain administrator/integration unavailable'; END IF;
  IF NOT EXISTS (SELECT 1 FROM operations.north_client_registry WHERE agency_slug='north')
  THEN RAISE EXCEPTION 'Initial North integration must already exist'; END IF;
  IF EXISTS (SELECT 1 FROM operations.north_client_registry
             WHERE north_client_id=ANY({clients}) AND agency_slug<>'north')
  THEN RAISE EXCEPTION 'Included UUID already belongs to another agency'; END IF;
  IF EXISTS (SELECT 1 FROM operations.north_client_registry
             WHERE north_client_id=ANY({excluded}) AND agency_slug<>'south')
  THEN RAISE EXCEPTION 'Excluded South UUID has conflicting registry agency'; END IF;
END
$guard$;
WITH inserted AS (
  INSERT INTO operations.north_client_registry(north_client_id,agency_slug)
  SELECT client_id,'north' FROM unnest({clients}) AS ids(client_id)
  ON CONFLICT(north_client_id) DO NOTHING
  RETURNING north_client_id
)
SELECT jsonb_build_object(
  'operation','extend-north-registry',
  'admin_app_user_id','{admin}',
  'requested_count',{len(manifest['clients'])},
  'inserted_count',count(*),
  'inserted_ids',coalesce(jsonb_agg(north_client_id ORDER BY north_client_id),'[]'::jsonb),
  'rollback_sql',CASE WHEN count(*)=0 THEN '-- No registry rows were inserted.' ELSE
    format('BEGIN; SET LOCAL lock_timeout=''5s''; LOCK TABLE operations.north_client_registry IN SHARE ROW EXCLUSIVE MODE; DELETE FROM operations.north_client_registry WHERE agency_slug=''north'' AND north_client_id IN (%s) RETURNING north_client_id; COMMIT;',
      string_agg(quote_literal(north_client_id::text)||'::uuid',',' ORDER BY north_client_id)) END
) FROM inserted;
COMMIT;
"""


def secure_write(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(content)


def verify_review(sql: bytes, expected: bytes, reviewed: str | None) -> str:
    digest = hashlib.sha256(sql).hexdigest()
    if not reviewed or digest != reviewed or sql != expected:
        raise ValueError('SQL must match both reviewed SHA-256 and current manifest generation')
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--write', type=Path, metavar='PRIVATE_DIRECTORY')
    mode.add_argument('--apply-sql', type=Path)
    parser.add_argument('--reviewed-sql-sha256')
    parser.add_argument('--audit-out', type=Path)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text())
    manifest = validate_manifest(data)
    sql = build_sql(data)
    digest = hashlib.sha256(sql.encode()).hexdigest()
    summary = {'mode': 'dry-run', 'sql_sha256': digest,
               'clients': len(manifest['clients']), 'excluded': len(manifest['excluded']),
               'approval_reference': manifest['approval_reference']}
    if args.write:
        args.write.mkdir(mode=0o700, parents=True, exist_ok=True)
        if args.write.stat().st_mode & 0o077:
            raise ValueError('Output directory must have private permissions (0700)')
        secure_write(args.write / 'reviewed.sql', sql)
        secure_write(args.write / 'review.json', json.dumps(summary, indent=2) + '\n')
        summary['mode'] = 'written'
    elif args.apply_sql:
        verify_review(args.apply_sql.read_bytes(), sql.encode(), args.reviewed_sql_sha256)
        if not args.audit_out or args.audit_out.exists():
            raise ValueError('Apply requires a new --audit-out file')
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError('Private DATABASE_URL environment is required for apply')
        if not args.audit_out.parent.is_dir() or args.audit_out.parent.stat().st_mode & 0o077:
            raise ValueError('Audit parent must already exist with private permissions (0700)')
        # Avoid credentials in argv and do not relay secret-bearing psql errors.
        env = dict(os.environ, PGDATABASE=database_url, PGCONNECT_TIMEOUT='10')
        # Reserve and test the private audit sink before any database mutation.
        fd = os.open(args.audit_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as audit_file:
            audit_file.write(json.dumps({'status': 'pending', 'sql_sha256': digest}) + '\n')
            audit_file.flush(); os.fsync(audit_file.fileno())
            result = subprocess.run(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A'],
                                    input=sql, env=env, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError('Registry apply failed; inspect private database logs. Audit remains pending; verify database state before retry.')
            audit = json.loads(result.stdout.strip())
            audit.update(status='committed', sql_sha256=digest,
                         approval_reference=manifest['approval_reference'])
            audit_file.seek(0); audit_file.truncate()
            audit_file.write(json.dumps(audit, indent=2) + '\n')
            audit_file.flush(); os.fsync(audit_file.fileno())
        summary.update(mode='applied', inserted_count=audit['inserted_count'])
    elif args.reviewed_sql_sha256 or args.audit_out:
        raise ValueError('Review digest and audit-out apply only to --apply-sql')
    print(json.dumps(summary))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from None
