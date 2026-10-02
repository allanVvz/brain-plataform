"""Pure env-override tests; never invokes Docker or connects to a service."""
import json, pathlib, subprocess, sys, tempfile, unittest
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
 def test_new_keys_removed_by_rollback(self):
  desired={**dict.fromkeys(FLAGS,'false'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true','NEW':'value'}
  c,r=self.render('operations-api',{'OLD':'value'},desired,False)
  self.assertIsNone(r['environment']['NEW']);self.assertEqual(r['environment']['OLD'],'value')
class NativeGateDiagnostics(unittest.TestCase):
 def smoke(self, failure):
  fixture={'approved':True,'isolated':True,'agency_slug':'north',
   'brainId':'11111111-1111-4111-8111-111111111111',
   'northId':'22222222-2222-4222-8222-222222222222',
   'clientId':'33333333-3333-4333-8333-333333333333',
   'fixtureTaskId':'44444444-4444-4444-8444-444444444444',
   'foreignTaskId':'55555555-5555-4555-8555-555555555555',
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
 if(path.endsWith('/auth/me'))return Response.json({user:{id:testFixture.brainId,role:'user',account_type:'agency'},personas:[],navigation:{allowed_portals:['north']}});
 if(path.endsWith('/revoke')){testRevoked=true;console.log('TEST_REVOCATION=called');return Response.json({revoked:true});}
 throw Error('PRIVATE_UNEXPECTED_URL_SENTINEL');
};
'''.replace('FIXTURE',json.dumps(fixture)).replace('FAILURE',json.dumps(failure))
  source=source.replace("import {createAdapterFromEnvironment} from '/app/dist/src/adapter.js';",stub)
  return subprocess.run(['node','--input-type=module','-e',source],input=json.dumps(fixture),capture_output=True,text=True)
 def test_fixed_failure_stages_and_cleanup_without_secret_logging(self):
  for stage in ['delegation_context','native_session']:
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

if __name__=='__main__':unittest.main()
