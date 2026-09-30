// Private API protocol test only: NOT login E2E and NOT a browser session.
// Run inside operations container with its runtime shared HMAC; coordinator verifies gateway parity.
import {createHmac,createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {Pool} from 'pg';
const secret=process.env.BRAIN_INTERNAL_AUTH_SECRET;
if(!secret||Buffer.byteLength(secret)<32){console.log(JSON.stringify({mode:'internal_api_only',blocked:true,reason:'runtime_hmac_unavailable'}));process.exit(2);}
const base=new URL(process.env.AKIA_SMOKE_INTERNAL_ORIGIN||'http://127.0.0.1:8096');
if(base.protocol!=='http:'||!['127.0.0.1','localhost','operations-api'].includes(base.hostname)||base.username||base.password||base.pathname!=='/'||base.search||base.hash)throw new Error('private service origin required');
function signedHeaders(){
 const now=Math.floor(Date.now()/1000),principal=Buffer.from(JSON.stringify({iss:'brain-gateway',sub:'c1037b25-99e7-4149-80f1-f502b1ac34c0',iat:now,exp:now+90,portal_scope:'north'})).toString('base64url');
 return {'x-brain-principal':principal,'x-brain-principal-signature':createHmac('sha256',secret).update(principal,'ascii').digest('hex')};
}
const expected=["0d6167c2-acb5-4d3b-a0e7-a713f0d3d7a2", "1b479f4d-f7aa-4ec0-a560-e77df4bb2f7a", "3cd4acdc-67fd-4524-8e8c-e2b4192ad55d", "4212adc0-2853-4779-8e26-6c0e5ecfdd74", "4f2bfda6-325d-4da3-94ff-c64802e1e2a4", "59a0d50c-40ba-4afc-b4fd-d73c9bc4c585", "7698938b-f762-4116-8926-b13abf82d809", "d7cdbac3-775d-457f-b25a-dbf899687853", "ec085c64-e40a-4652-b5e2-e0074012687c", "ef3f86b3-03ee-4e9a-96d5-f897bab1aafa", "f1bb7a9f-1d92-4304-b43a-0b0ef6c499be"].sort(),checks=[];
async function call(path,override={}){return fetch(new URL(path,base),{redirect:'error',signal:AbortSignal.timeout(20000),headers:{...signedHeaders(),...override}});}
function assert(check,passed,status,extra={}){checks.push({check,passed:!!passed,status,...extra});if(!passed)throw new Error('check_failed');}
try{
 assert('cron_execution_disabled',process.env.OPERATIONS_CRON_ENABLED!=='true'&&process.env.NORTH_CANONICAL_EXECUTION_ENABLED!=='true',200);
 const runtime='/app/src/north-automation/generated/';
 const bundle=await readFile(runtime+'canonical.mjs');const bundleHash='c43c8958fde97b19e37f31ee4f740dac6161b0098856fc745440c4fe1f8c9ac1';
 assert('canonical_bundle_checksum',createHash('sha256').update(bundle).digest('hex')===bundleHash,200);
 const {createJobs}=await import(runtime+'runtime.mjs');process.env.NORTH_CANONICAL_REVIEWED_SHA256=bundleHash;
 const pool=new Pool({connectionString:process.env.DATABASE_URL,max:1});
 try{const jobs=await createJobs(pool);const plan=await jobs.dryRun(new Intl.DateTimeFormat('en-CA',{timeZone:'America/Sao_Paulo'}).format(new Date()));assert('canonical_planner_only',plan.status==='dry-run'&&plan.mutations===0,200,{configs:plan.plan.length,mutations:plan.mutations});}finally{await pool.end();}
 const a=await call('/api/operations/portal-access');assert('portal_access_http',a.status===200,a.status);const grant=await a.json();assert('portal_access_grant',grant.portal_scope==='north'&&grant.allowed===true,a.status);
 const c=await call('/api/operations/clients');assert('clients_http',c.status===200,c.status);const clients=await c.json();assert('exact_clients',Array.isArray(clients)&&JSON.stringify(clients.map(x=>x.id).sort())===JSON.stringify(expected),c.status,{count:Array.isArray(clients)?clients.length:0});
 for(const id of expected){const r=await call(`/api/operations/tasks?clientId=${id}`);assert('tasks_http',r.status===200,r.status,{clientId:id});const b=await r.json();assert('tasks_scope',b.clientId===id&&Array.isArray(b.tasks)&&b.tasks.every(x=>x.client_id===id),r.status,{clientId:id,count:Array.isArray(b.tasks)?b.tasks.length:0});}
 const r=await call('/api/operations/tasks?clientId=00000000-0000-4000-8000-000000000000');assert('ungranted_client_denied',r.status===403,r.status);
 const south=await call('/api/operations/tasks?clientId=4b6491e0-d453-477b-a71e-b1e3c79f65d8');assert('south_tock_fatal_denied',south.status===403,south.status);
 const invalid=await call('/api/operations/clients',{'x-brain-principal-signature':'0'.repeat(64)});assert('invalid_signature_denied',invalid.status===401,invalid.status);
 for(const resource of ['clients-bootstrap','shell','cards','routines','task-types','automations','automations/runs','automations/daily/options','performance/templates','assignees']){
  const response=await call('/api/operations/north/'+resource);assert('original_'+resource+'_http',response.status===200,response.status);
  const body=await response.json();
  if(resource==='automations')assert('original_automations_scope',body.automations.length>0&&body.automations.every(c=>expected.includes(c.targetTask.clientId)),response.status,{count:body.automations.length});
  if(resource==='automations/runs')assert('original_automation_history',body.runs.length>0,response.status,{count:body.runs.length});
  if(resource==='clients-bootstrap')assert('original_exact_clients',JSON.stringify(body.clients.map(c=>c.id).sort())===JSON.stringify(expected),response.status,{count:body.clients.length,leads:body.leads.length});
  if(resource==='cards'||resource==='routines')assert('original_'+resource+'_scope',Array.isArray(body.tasks)&&body.tasks.every(t=>expected.includes(t.client_id)),response.status,{count:body.tasks?.length});
 }
 const write=await fetch(new URL('/api/operations/north/tasks',base),{method:'POST',headers:signedHeaders(),redirect:'error',signal:AbortSignal.timeout(20000)});assert('mutations_disabled',write.status===405,write.status);
 console.log(JSON.stringify({mode:'internal_api_only',login_e2e:false,passed:true,checks}));
}catch{console.log(JSON.stringify({mode:'internal_api_only',login_e2e:false,passed:false,checks,error:'smoke_failed_no_response_data_logged'}));process.exitCode=1;}
