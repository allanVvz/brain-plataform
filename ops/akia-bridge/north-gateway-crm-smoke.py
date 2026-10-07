import json
import os
import urllib.error
import urllib.request


assert os.environ.get('AKIA_CRM_ENABLED') == 'true'
origins = json.loads(os.environ['AKIA_PORTAL_PATH_ORIGINS'])['north']
assert 'https://test.north-portal.pages.dev' in origins
request = urllib.request.Request(
    'http://127.0.0.1:8080/portal-api/north/portal/client-pages?persona_slug=probe',
    headers={'Host': os.environ['AKIA_PORTAL_PATH_HOST'], 'Origin': origins[0]},
)
try:
    urllib.request.urlopen(request, timeout=5)
except urllib.error.HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError('anonymous CRM request was accepted')
print('NORTH_GATEWAY_CRM_BOUNDARY=passed')
