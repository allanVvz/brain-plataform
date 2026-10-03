# Real fixture login through candidate gateway. No business mutation.
import json, sys, urllib.request, urllib.error, http.cookiejar, os, re
failed = False
stage = "fixture"
failure_stage = None
jar = http.cookiejar.CookieJar()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
# Secure cookies cannot be replayed by CookieJar over internal HTTP. Keep the
# exact cookie privately and pass it explicitly; production origin remains TLS.
cookie = None

def call(path, method='GET', data=None):
    origins=json.loads(os.environ['AKIA_PORTAL_PATH_ORIGINS'])['north']
    origin=origins[0] if isinstance(origins,list) else origins
    assert origin.startswith('https://')
    headers = {'Host': os.environ['AKIA_PORTAL_PATH_HOST'], 'Origin': origin}
    if cookie: headers['Authorization'] = 'Bearer '+cookie
    if data is not None: headers['Content-Type'] = 'application/json'
    req = urllib.request.Request('http://127.0.0.1:8080/portal-api/north/'+path,
        data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
    try:
        with client.open(req, timeout=15) as r: return r.status, json.loads(r.read() or b'{}'), r.headers
    except urllib.error.HTTPError as e: return e.code, {}, e.headers
try:
    f = json.load(sys.stdin)
    assert f['approved'] is True and f['isolated'] is True and f['agency_slug'] == 'north'
    assert all(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',f[k]) for k in ('brainId','northId','clientId','fixtureTaskId','foreignTaskId'))
    assert f['fixtureTaskId'] != f['foreignTaskId']
    stage = "login"
    status, session, headers = call('auth/login', 'POST', {'identifier': f['email'], 'password': f['password']})
    cookie = session.get('session_token')
    assert status == 200 and cookie
    stage = "identity"
    status, me, _ = call('auth/me')
    assert status == 200 and me['user']['id'] == f['brainId'] and me['user']['role'] == 'user'
    assert me['user']['account_type'] == 'agency' and me['personas'] == []
    stage = "global_capabilities"
    status, caps, _ = call('api/operations/north/capabilities')
    assert status == 200 and all(caps.get(k) is True for k in ('task_text_edit','client_edit','settings_edit'))
    stage = "fixture_task_capabilities"
    status, caps, _ = call('api/operations/north/tasks/'+f['fixtureTaskId']+'/capabilities')
    assert status == 200 and all(caps.get(k) is True for k in ('comments_create','comments_edit_own','task_edit'))
    assert caps.get('comments_delete') is False and caps.get('async_effects') is False
    stage = "foreign_task_denial"
    assert call('api/operations/north/tasks/'+f['foreignTaskId']+'/capabilities')[0] == 403
except Exception:
    failed = True
    failure_stage = stage
finally:
    if cookie:
        try:
            assert call('auth/logout', 'POST', {})[0] == 200
            # Reusing a revoked session must deny delegated capabilities, even
            # if Brain stateless /auth/me still accepts the signed session.
            assert call('api/operations/north/tasks/'+f['fixtureTaskId']+'/capabilities')[0] in (401,403)
        except Exception:
            failed = True
            failure_stage = failure_stage or "logout_revocation"
if failure_stage: print('NORTH_GATEWAY_ACTIVATION_STAGE='+failure_stage)
print('NORTH_GATEWAY_ACTIVATION_AUTH=' + ('failed' if failed else 'passed'))
sys.exit(1 if failed else 0)
