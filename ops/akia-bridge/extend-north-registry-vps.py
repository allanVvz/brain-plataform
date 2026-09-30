#!/usr/bin/env python3
"""Run a reviewed registry extension on the existing VPS database container."""
import argparse, hashlib, importlib.util, json, os, subprocess
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--generator',type=Path,required=True)
p.add_argument('--brain-root',type=Path,required=True)
p.add_argument('--reviewed-sha256',required=True)
p.add_argument('--apply',action='store_true')
a=p.parse_args()
spec=importlib.util.spec_from_file_location('registry',a.generator)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
manifest=json.loads(os.environ['AKIA_EXPANDED_CLIENTS_MANIFEST'])
sql=module.build_sql(manifest)
if hashlib.sha256(sql.encode()).hexdigest()!=a.reviewed_sha256: raise SystemExit('Registry SQL digest mismatch')
container='brain-ai-db-1'
raw=subprocess.run(['docker','inspect','--format','{{json .Config.Env}}',container],check=True,capture_output=True,text=True).stdout
env=dict(v.split('=',1) for v in json.loads(raw) if '=' in v)
def query(text):
 result=subprocess.run(['docker','exec','-i',container,'psql','-X','-q','-v','ON_ERROR_STOP=1','-t','-A','-U',env.get('POSTGRES_USER','postgres'),'-d',env.get('POSTGRES_DB','postgres')],input=text,capture_output=True,text=True)
 if result.returncode: raise SystemExit('Registry validation/apply failed; inspect private database logs')
 return json.loads(result.stdout.strip())
# Exercise the exact constraints and inserts without retaining any row.
if not sql.endswith('COMMIT;\n'): raise SystemExit('Unsupported transaction terminator')
preview=query(sql.removesuffix('COMMIT;\n')+'ROLLBACK;\n')
print(json.dumps({'mode':'transaction_rollback_dry_run','requested':preview['requested_count'],'would_insert':preview['inserted_count'],'sql_sha256':a.reviewed_sha256}))
if a.apply:
 folder=a.brain_root/'secrets'/'akia-registry-audits';folder.mkdir(mode=0o700,exist_ok=True)
 if folder.stat().st_mode & 0o077: raise SystemExit('Audit folder must be private')
 path=folder/(a.reviewed_sha256+'.json')
 if path.exists(): raise SystemExit('An audit for this change exists; verify state before retrying')
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as handle:
  handle.write(json.dumps({'status':'pending','sql_sha256':a.reviewed_sha256})+'\n');handle.flush();os.fsync(handle.fileno())
  result=query(sql);result.update(status='committed',sql_sha256=a.reviewed_sha256,approval_reference=manifest['approval_reference'])
  handle.seek(0);handle.truncate();handle.write(json.dumps(result,indent=2)+'\n');handle.flush();os.fsync(handle.fileno())
 print(json.dumps({'mode':'applied','requested':result['requested_count'],'inserted':result['inserted_count'],'sql_sha256':a.reviewed_sha256}))
