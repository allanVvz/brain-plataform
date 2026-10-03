"""Pure env-override tests; never invokes Docker or connects to a service."""
import json, pathlib, re, shutil, subprocess, sys, tempfile, unittest
SOURCE=pathlib.Path(__file__).with_name('release-akia-service.sh').read_text().split("<<'PY'\n",1)[1].split('\nPY',1)[0]
FLAGS=['NORTH_RUNTIME_COMMENTS_ENABLED','NORTH_RUNTIME_TASK_EDIT_ENABLED','NORTH_RUNTIME_CLIENT_EDIT_ENABLED','NORTH_RUNTIME_SETTINGS_ENABLED']
class Controls(unittest.TestCase):
 def render(self,unit,old,desired,activate=True):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)
   (p/'desired-config.json').write_text(json.dumps({'services':{unit:{'environment':desired}}}))
   (p/'old-inspect.json').write_text(json.dumps([{'Config':{'Image':'old@sha256:'+'a'*64,'Env':[k+'='+v for k,v in old.items()]}}]))
   r=subprocess.run([sys.executable,'-c',SOURCE,d,unit,'new@sha256:'+'b'*64,str(activate).lower()],capture_output=True)
   if r.returncode:return None
   return tuple(json.loads((p/name).read_text())['services'][unit] for name in ['candidate.json','rollback.json'])
 def test_operations_activation_only_flags_preserves_dollars(self):
  old={**dict.fromkeys(FLAGS,'false'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true','SECRET':'a$b${c}'}
  candidate,rollback=self.render('operations-api',old,{'UNRELATED':'must-not-enter'})
  self.assertEqual(set(candidate['environment']),set(old))
  for k in FLAGS:self.assertEqual(candidate['environment'][k],'true');self.assertEqual(rollback['environment'][k],'false')
  self.assertEqual(candidate['environment']['SECRET'],'a$$b$${c}')
  self.assertEqual(rollback['image'],'old@sha256:'+'a'*64)
 def test_gateway_only_delegation(self):
  old={'SECRET':'opaque','AKIA_NORTH_DELEGATION_ENABLED':'false'}
  c,r=self.render('akia-gateway',old,{'UNRELATED':'no'})
  self.assertEqual(c['environment'],{**old,'AKIA_NORTH_DELEGATION_ENABLED':'true'})
  self.assertEqual(r['environment'],old)
 def test_gateway_rollout_preserves_active_delegation_and_enables_crm(self):
  old={'AKIA_NORTH_DELEGATION_ENABLED':'true','AKIA_CRM_ENABLED':'false','SECRET':'opaque'}
  c,r=self.render('akia-gateway',old,{'AKIA_CRM_ENABLED':'true','SECRET':'opaque'},False)
  self.assertEqual(c['environment']['AKIA_NORTH_DELEGATION_ENABLED'],'true')
  self.assertEqual(c['environment']['AKIA_CRM_ENABLED'],'true')
  self.assertEqual(r['environment'],old)
 def test_gateway_activation_rechecks_active_delegation_without_dropping_crm(self):
  old={'AKIA_NORTH_DELEGATION_ENABLED':'true','AKIA_CRM_ENABLED':'true','SECRET':'opaque'}
  c,r=self.render('akia-gateway',old,{'AKIA_CRM_ENABLED':'true'},True)
  self.assertEqual(c['environment'],old)
  self.assertEqual(r['environment'],old)
 def test_invalid_stage_rejected(self):
  self.assertIsNone(self.render('operations-api',{},{}))
 def test_operations_rollout_preserves_enabled_actions_and_rollback(self):
  desired={**dict.fromkeys(FLAGS,'false'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true'}
  old={**desired,**dict.fromkeys(FLAGS,'true'),'SECRET':'private'}
  candidate,rollback=self.render('operations-api',old,desired,False)
  for key in FLAGS:self.assertEqual(candidate['environment'][key],'true')
  self.assertEqual(rollback['environment'],{**old,'NORTH_RUNTIME_DRIVE_ENABLED':None,'NORTH_RUNTIME_CLIENT_CREATE_ENABLED':None})
 def test_new_keys_removed_by_rollback(self):
  desired={**dict.fromkeys(FLAGS,'false'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true','NEW':'value'}
  c,r=self.render('operations-api',{'OLD':'value'},desired,False)
  self.assertIsNone(r['environment']['NEW']);self.assertEqual(r['environment']['OLD'],'value')
 def test_active_compose_rollout_preserves_mixed_flags(self):
  desired={**dict.fromkeys(FLAGS,'true'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true'}
  old={**desired,FLAGS[1]:'false'}
  c,r=self.render('operations-api',old,desired,False)
  for key in FLAGS:self.assertEqual(c['environment'][key],old[key])
  self.assertEqual(r['environment'][FLAGS[1]],'false')
 def test_operations_cron_allows_only_audited_dry_run(self):
  old={**dict.fromkeys(FLAGS,'true'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true','OPERATIONS_CRON_ENABLED':'true','OPERATIONS_CRON_DRY_RUN':'true','NORTH_CANONICAL_EXECUTION_ENABLED':'false'}
  self.assertIsNotNone(self.render('operations-api',old,old,False))
  self.assertIsNone(self.render('operations-api',old,{**old,'OPERATIONS_CRON_DRY_RUN':'false'},False))
  self.assertIsNone(self.render('operations-api',old,{**old,'NORTH_CANONICAL_EXECUTION_ENABLED':'true'},False))
class NativeGateDiagnostics(unittest.TestCase):
 def smoke(self, failure):
  fixture={'approved':True,'isolated':True,'agency_slug':'north',
   'brainId':'11111111-1111-4111-8111-111111111111',
   'northId':'22222222-2222-4222-8222-222222222222',
   'clientId':'33333333-3333-4333-8333-333333333333',
   'fixtureTaskId':'44444444-4444-4444-8444-444444444444',
   'foreignTaskId':'55555555-5555-4555-8555-555555555555',
   'foreignClientId':'77777777-7777-4777-8777-777777777777',
   'email':'private-fixture@example.invalid','password':'PRIVATE_PASSWORD_SENTINEL'}
  source=pathlib.Path(__file__).with_name('deploy-akia-north-runtime.sh').read_text().split("<<'JS'\n",1)[1].split('\nJS',1)[0]
  stub=r'''
const testFixture=FIXTURE, testFailure=FAILURE;let testRevoked=false;
process.env.BRAIN_INTERNAL_AUTH_SECRET='PRIVATE_SECRET_SENTINEL';
process.env.NORTH_OPERATIONS_PRIVATE_URL='http://operations.test';
const testContext={northProfileId:testFixture.northId,brainUserId:testFixture.brainId,
 northDelegationId:'66666666-6666-4666-8666-666666666666',agency:'north',northRole:'admin',
 allowedClientIds:new Set([testFixture.clientId])};
const failAt=(stage)=>{if(testFailure===stage)throw Error('PRIVATE_PROVIDER_ERROR_SENTINEL');};
const createAdapterFromEnvironment=()=>({ready:async()=>true,
 resolve:async()=>{failAt('delegation_context');return testContext;},
 revalidate:async()=>!testRevoked,
 sessions:{get:async()=>{failAt('native_session');return {northProfileId:testFixture.northId};},invalidate:()=>{}},
 scoped:async()=>({taskDto:async()=>({id:testFixture.fixtureTaskId,client_id:testFixture.clientId}),task:async()=>null})});
globalThis.fetch=async(url)=>{
 const path=new URL(url).pathname;
 if(path.endsWith('/auth/login')){
  const token=Buffer.from(JSON.stringify({sub:testFixture.brainId,exp:Math.floor(Date.now()/1000)+300})).toString('base64url')+'.signature';
  return new Response('{}',{headers:{'Set-Cookie':'ai_brain_session='+token+'; HttpOnly'}});
 }
 if(path.endsWith('/auth/me'))return Response.json({user:{id:testFixture.brainId,role:'user',account_type:'agency'},personas:[],navigation:{surface:'operations',home_url:'/north/admin'}});
 if(path.endsWith('/portal-access'))return Response.json({portal_scope:'north',allowed:testFailure!=='portal_access'});
 if(path.endsWith('/context'))return Response.json({brainUserId:testFixture.brainId,northProfileId:testFixture.northId,allowedClientIds:[testFixture.clientId]});
 if(path.endsWith('/revoke')){testRevoked=true;console.log('TEST_REVOCATION=called');return Response.json({revoked:true});}
 throw Error('PRIVATE_UNEXPECTED_URL_SENTINEL');
};
'''.replace('FIXTURE',json.dumps(fixture)).replace('FAILURE',json.dumps(failure))
  source=source.replace("import {createAdapterFromEnvironment} from '/app/dist/src/adapter.js';",stub)
  return subprocess.run(['node','--input-type=module','-e',source],input=json.dumps(fixture),capture_output=True,text=True)
 def test_fixed_failure_stages_and_cleanup_without_secret_logging(self):
  for stage in ['delegation_context','native_session','portal_access']:
   with self.subTest(stage=stage):
    result=self.smoke(stage)
    self.assertEqual(result.returncode,1)
    self.assertIn('NORTH_NATIVE_CONTRACT=failed stage='+stage,result.stderr)
    self.assertIn('TEST_REVOCATION=called',result.stdout)
    self.assertNotIn('PRIVATE_',result.stdout+result.stderr)
    self.assertNotIn('private-fixture',result.stdout+result.stderr)
 def test_success_retains_native_contract_and_revocation(self):
  result=self.smoke(None)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('NORTH_NATIVE_CONTRACT=passed',result.stdout)
  self.assertIn('revocation=verified',result.stdout)
  self.assertEqual(result.stderr,'')

class NorthRuntimeWorkerRelease(unittest.TestCase):
 script=pathlib.Path(__file__).with_name('deploy-akia-north-runtime.sh').read_text()
 prepare=script.split("<<'PY'\n",1)[1].split('\nPY',1)[0]
 def test_private_candidate_false_preserves_original_and_unrelated_bytes(self):
  for worker in [b'',b'NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED=true\n',b'NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED="false"\n',b'export NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED = true\nNORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED=false\n']:
   with self.subTest(worker=worker),tempfile.TemporaryDirectory() as d:
    root=pathlib.Path(d);original=root/'original.env';candidate=root/'candidate.env'
    unrelated=b'PRIVATE_SECRET=a$b${c}\nOTHER="quoted value"\n'
    original.write_bytes(unrelated+worker);original.chmod(0o600);shutil.copyfile(original,candidate);candidate.chmod(0o600)
    result=subprocess.run([sys.executable,'-c',self.prepare,str(candidate)],capture_output=True)
    self.assertEqual(result.returncode,0)
    self.assertEqual(candidate.read_bytes(),unrelated+b'NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED=false\n')
    self.assertEqual(original.read_bytes(),unrelated+worker)
    self.assertEqual(candidate.stat().st_mode&0o777,0o600)
    self.assertEqual(result.stdout+result.stderr,b'')
 def worker_check(self,env):
  function='worker_disabled(){'+self.script.split('worker_disabled(){',1)[1].split('\nverify(){',1)[0]
  # Substitute only inspect's JSON transport. No Docker binary or stack runs.
  function=function.replace('docker inspect --format \'{{json .Config.Env}}\' "$1"','cat "$TEST_ENV_JSON"')
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'env.json';p.write_text(json.dumps(env))
   return subprocess.run(['bash','-c',function+'\nworker_disabled candidate'],env={'PATH':'/usr/bin:/bin','TEST_ENV_JSON':str(p)},capture_output=True,text=True)
 def test_effective_worker_guard_denies_missing_true_and_duplicate_flags(self):
  for values in [[],['true'],['false','true'],['false','false']]:
   result=self.worker_check(['PRIVATE_SECRET=sentinel']+['NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED='+v for v in values])
   self.assertNotEqual(result.returncode,0)
   self.assertNotIn('verified_false',result.stdout)
   self.assertNotIn('sentinel',result.stdout+result.stderr)
 def test_effective_worker_guard_accepts_exact_false(self):
  result=self.worker_check(['PRIVATE_SECRET=sentinel','NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED=false'])
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('AKIA_RUNTIME_WORKER=verified_false',result.stdout)
  self.assertNotIn('sentinel',result.stdout+result.stderr)
 def test_rollback_checks_original_effective_env_including_absent_worker(self):
  line=next(line for line in self.script.splitlines() if 'runtime rollback effective env differs' in line)
  code=re.search(r"python3 -c '([^']+)'",line).group(1)
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'original.json';original=['PRIVATE_SECRET=a$b','NORTH_RUNTIME_COMMENTS_ENABLED=true'];p.write_text(json.dumps(original))
   for actual,expected_code in [(original,0),(original+['NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED=false'],1),(['PRIVATE_SECRET=changed'],1)]:
    result=subprocess.run([sys.executable,'-c',code,str(p)],input=json.dumps(actual),capture_output=True,text=True)
    self.assertEqual(result.returncode,expected_code)
    self.assertNotIn('PRIVATE_SECRET',result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
