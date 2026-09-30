// Private API protocol test only: NOT login E2E and NOT a browser session.
// Run inside operations container with its runtime shared HMAC; coordinator verifies gateway parity.
import {createHmac} from 'node:crypto';
const secret=process.env.BRAIN_INTERNAL_AUTH_SECRET;
if(!secret||Buffer.byteLength(secret)<32){console.log(JSON.stringify({mode:'internal_api_only',blocked:true,reason:'runtime_hmac_unavailable'}));process.exit(2);}
const base=new URL(process.env.AKIA_SMOKE_INTERNAL_ORIGIN||'http://127.0.0.1:8096');
if(base.protocol!=='http:'||!['127.0.0.1','localhost','operations-api'].includes(base.hostname)||base.username||base.password||base.pathname!=='/'||base.search||base.hash)throw new Error('private service origin required');
const now=Math.floor(Date.now()/1000),principal=Buffer.from(JSON.stringify({iss:'brain-gateway',sub:'c1037b25-99e7-4149-80f1-f502b1ac34c0',iat:now,exp:now+90,portal_scope:'north'})).toString('base64url');
const signature=createHmac('sha256',secret).update(principal,'ascii').digest('hex');
const headers={'x-brain-principal':principal,'x-brain-principal-signature':signature};
const expected=['ec085c64-e40a-4652-b5e2-e0074012687c','1b479f4d-f7aa-4ec0-a560-e77df4bb2f7a'].sort(),checks=[];
async function call(path,override={}){return fetch(new URL(path,base),{redirect:'error',signal:AbortSignal.timeout(20000),headers:{...headers,...override}});}
function assert(check,passed,status,extra={}){checks.push({check,passed:!!passed,status,...extra});if(!passed)throw new Error('check_failed');}
try{
 const a=await call('/api/operations/portal-access');assert('portal_access_http',a.status===200,a.status);const grant=await a.json();assert('portal_access_grant',grant.portal_scope==='north'&&grant.allowed===true,a.status);
 const c=await call('/api/operations/clients');assert('clients_http',c.status===200,c.status);const clients=await c.json();assert('exact_clients',Array.isArray(clients)&&JSON.stringify(clients.map(x=>x.id).sort())===JSON.stringify(expected),c.status,{count:Array.isArray(clients)?clients.length:0});
 for(const id of expected){const r=await call(`/api/operations/tasks?clientId=${id}`);assert('tasks_http',r.status===200,r.status,{clientId:id});const b=await r.json();assert('tasks_scope',b.clientId===id&&Array.isArray(b.tasks)&&b.tasks.every(x=>x.client_id===id),r.status,{clientId:id,count:Array.isArray(b.tasks)?b.tasks.length:0});}
 const r=await call('/api/operations/tasks?clientId=00000000-0000-4000-8000-000000000000');assert('ungranted_client_denied',r.status===403,r.status);
 const invalid=await call('/api/operations/clients',{'x-brain-principal-signature':'0'.repeat(64)});assert('invalid_signature_denied',invalid.status===401,invalid.status);
 console.log(JSON.stringify({mode:'internal_api_only',login_e2e:false,passed:true,checks}));
}catch{console.log(JSON.stringify({mode:'internal_api_only',login_e2e:false,passed:false,checks,error:'smoke_failed_no_response_data_logged'}));process.exitCode=1;}
