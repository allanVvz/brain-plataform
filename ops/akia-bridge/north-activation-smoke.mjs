// Candidate capability/auth gate. Sessions only; no business mutations.
import fs from 'node:fs';import {createHmac} from 'node:crypto';
const check=x=>{if(!x)throw Error('North activation gate failed');};
const secret=process.env.BRAIN_INTERNAL_AUTH_SECRET,base='http://127.0.0.1:8096',control='http://caddy:8090/control-plane';
let cookie,principal;
const request=async(url,options={})=>fetch(url,{...options,redirect:'error',signal:AbortSignal.timeout(15000)});
try{
const f=JSON.parse(fs.readFileSync(0,'utf8')),uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(v);
check(f.approved===true&&f.isolated===true&&f.agency_slug==='north'&&[f.brainId,f.northId,f.clientId,f.fixtureTaskId,f.foreignTaskId].every(uuid)&&f.fixtureTaskId!==f.foreignTaskId);
const login=await request(control+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:f.email,password:f.password})});check(login.ok);cookie=login.headers.getSetCookie().find(c=>c.startsWith('ai_brain_session='))?.split(';')[0];check(cookie);
const me=await request(control+'/auth/me',{headers:{cookie}}),session=await me.json();check(me.ok&&session.user?.id===f.brainId&&session.user.role==='user'&&session.user.account_type==='agency'&&session.personas?.length===0&&session.navigation?.allowed_portals?.includes('north'));
const token=cookie.slice('ai_brain_session='.length),claims=JSON.parse(Buffer.from(token.split('.')[0],'base64url').toString());check(claims.sub===f.brainId&&claims.exp*1000>Date.now());
const now=Math.floor(Date.now()/1000);principal={iss:'brain-gateway',aud:'operations-api',sub:f.brainId,portal_scope:'north',iat:now,exp:Math.min(now+120,claims.exp),north_delegation:{token_fingerprint:createHmac('sha256',secret).update('north-delegation-v1\0'+token,'ascii').digest('hex'),brain_expires_at:claims.exp}};
const headers=()=>{const encoded=Buffer.from(JSON.stringify(principal)).toString('base64url');return {'x-brain-principal':encoded,'x-brain-principal-signature':createHmac('sha256',secret).update(encoded,'ascii').digest('hex')};};
const contextResponse=await request(base+'/internal/v1/north-delegations/context',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:'{}'}),context=await contextResponse.json();
check(contextResponse.ok&&context.brainUserId===f.brainId&&context.northProfileId===f.northId&&context.allowedClientIds?.length===1&&context.allowedClientIds[0]===f.clientId&&context.internalClientIds?.length===1&&context.internalClientIds[0]===f.clientId);
const get=path=>request(base+'/api/operations/north/'+path,{headers:headers()});
const cap=await get('capabilities'),global=await cap.json();check(cap.ok&&global.task_text_edit===true&&global.client_edit===true&&global.settings_edit===true&&global.task_create===false&&global.drive_sync===false);
const task=await get('tasks/'+f.fixtureTaskId+'/capabilities'),c=await task.json();check(task.ok&&c.comments_create===true&&c.comments_edit_own===true&&c.task_edit===true&&c.comments_delete===false&&c.async_effects===false);
check((await get('tasks/'+f.foreignTaskId+'/capabilities')).status===403);
}catch{process.exitCode=1;}finally{
if(principal){try{const encoded=Buffer.from(JSON.stringify(principal)).toString('base64url');const r=await request(base+'/internal/v1/north-delegations/revoke',{method:'POST',headers:{'Content-Type':'application/json','x-brain-principal':encoded,'x-brain-principal-signature':createHmac('sha256',secret).update(encoded,'ascii').digest('hex')},body:'{}'});check(r.ok&&(await r.json()).revoked===true);}catch{process.exitCode=1;}}
if(cookie){try{check((await request(control+'/auth/logout',{method:'POST',headers:{cookie}})).ok);}catch{process.exitCode=1;}}
}
console.log('NORTH_ACTIVATION_CAPABILITY_AUTH='+(!process.exitCode?'passed':'failed'));
