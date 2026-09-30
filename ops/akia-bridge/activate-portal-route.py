#!/usr/bin/env python3
"""VPS only: insert one AKIA Caddy route; default is read-only dry-run."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render(original: bytes, host: str) -> bytes:
    text = original.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    headers = [r'\{\$API_DOMAIN\},\s*\{\$API_DOMAIN_SECONDARY\}', re.escape(host)]
    matches = list(re.finditer(r'(?m)^(?:' + '|'.join(headers) + r')\s*\{\s*\r?$', text))
    if len(matches) != 1:
        raise ValueError('Expected exactly one recognized API site block')
    start = matches[0].start()
    depth = 0
    end = None
    for line in text[start:].splitlines(keepends=True):
        code = line.split('#', 1)[0]
        depth += code.count('{') - code.count('}')
        start += len(line)
        if depth == 0:
            end = start
            break
    if end is None:
        raise ValueError('Unclosed API site block')
    begin = matches[0].start()
    block = text[begin:end]
    route = '\thandle /portal-api/* {' + newline + '\t\treverse_proxy akia-gateway:8080' + newline + '\t}' + newline
    if '/portal-api/' in block:
        if block.count('/portal-api/') == 1 and route in block:
            return original
        raise ValueError('Existing portal route differs; manual review required')
    marker = '\timport /etc/caddy/public-upstream.caddy' + newline
    if block.count(marker) != 1:
        raise ValueError('Expected one canonical upstream import in API site')
    offset = begin + block.index(marker)
    result = (text[:offset] + route + text[offset:]).encode('utf-8')
    if result.replace(route.encode(), b'', 1) != original:
        raise ValueError('Non-additive Caddy change rejected')
    return result


def command(*args: str) -> str:
    outcome = subprocess.run(args, capture_output=True, text=True)
    if outcome.returncode:
        # Caddy/docker errors can include interpolated configuration; withhold it.
        raise RuntimeError('Command failed: ' + ' '.join(args[:3]))
    return outcome.stdout.strip()


def request(url: str, origin: str | None = None, method: str = 'GET') -> tuple[int, dict, bytes]:
    headers = {'Origin': origin} if origin else {}
    if method == 'OPTIONS':
        headers.update({'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'authorization'})
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers, method=method), timeout=20) as response:
        return response.status, dict(response.headers), response.read(65536)


def probe(host: str, origin: str | None = None, portal: bool = False) -> None:
    base = 'https://' + host
    path = '/portal-api/north/health/ready' if portal else '/health'
    status, headers, body = request(base + path, origin if portal else None)
    payload = json.loads(body)
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError('Health probe failed')
    if portal:
        normalized = {key.lower(): value for key, value in headers.items()}
        if normalized.get('access-control-allow-origin') != origin or not (payload.get('ready') is True or payload.get('status') == 'ready'):
            raise RuntimeError('Portal readiness/CORS failed')
        status, headers, _ = request(base + '/portal-api/north/api/operations/clients', origin, 'OPTIONS')
        normalized = {key.lower(): value for key, value in headers.items()}
        if status != 204 or normalized.get('access-control-allow-origin') != origin:
            raise RuntimeError('Portal preflight failed')


def atomic_write(path: Path, content: bytes, original_stat: os.stat_result) -> None:
    fd, temp = tempfile.mkstemp(prefix='.akia-route-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), original_stat.st_mode & 0o777)
            os.fchown(handle.fileno(), original_stat.st_uid, original_stat.st_gid)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brain-root', type=Path, default=Path('/opt/brain-ai'))
    parser.add_argument('--project', default='brain-ai')
    parser.add_argument('--api-host', default='api.vzforeal.com')
    parser.add_argument('--north-origin', default='https://north-portal.pages.dev')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9.-]+', args.api_host):
        raise ValueError('Invalid API hostname')
    if args.north_origin != 'https://north-portal.pages.dev':
        raise ValueError('Use the reviewed exact North origin')
    active = args.brain_root.resolve() / '.deploy/caddy/Caddyfile'
    original = active.read_bytes()
    candidate = render(original, args.api_host)
    container = command('docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={args.project}', '--filter', 'label=com.docker.compose.service=caddy')
    if not container or len(container.splitlines()) != 1:
        raise RuntimeError('Exactly one running project Caddy is required')
    inspected = json.loads(command('docker', 'inspect', container))[0]
    mounts = [m for m in inspected['Mounts'] if m['Destination'] == '/etc/caddy']
    if len(mounts) != 1 or mounts[0]['Type'] != 'bind' or Path(mounts[0]['Source']).resolve() != active.parent:
        raise RuntimeError('Caddy must bind-mount the audited .deploy/caddy directory')
    env = dict(value.split('=', 1) for value in inspected['Config']['Env'] if '=' in value)
    if env.get('API_DOMAIN') != args.api_host:
        raise RuntimeError('API_DOMAIN in running Caddy does not match target')
    probe(args.api_host)
    print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'changed': candidate != original,
                      'before_sha256': digest(original), 'after_sha256': digest(candidate),
                      'target': str(active), 'brain_health': 'passed'}))
    if not args.apply:
        return
    state = args.brain_root.resolve() / '.deploy/akia'
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / 'portal-route.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if active.read_bytes() != original:
            raise RuntimeError('Caddy changed during preflight; rerun')
        if candidate == original:
            probe(args.api_host, args.north_origin, True)
            print('AKIA_PORTAL_ROUTE=already_active_verified')
            return
        stat = active.stat()
        backup = state / ('Caddyfile.before-portal-' + digest(original))
        if backup.exists() and backup.read_bytes() != original:
            raise RuntimeError('Backup checksum mismatch')
        if not backup.exists():
            with backup.open('xb') as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(original)
        fd, temp = tempfile.mkstemp(prefix='Caddyfile.akia-candidate-', dir=active.parent)
        os.close(fd)
        staging = Path(temp)
        changed = False
        try:
            staging.write_bytes(candidate)
            staging.chmod(stat.st_mode & 0o777)
            command('docker', 'exec', container, 'caddy', 'validate', '--config', '/etc/caddy/' + staging.name, '--adapter', 'caddyfile')
            if active.read_bytes() != original:
                raise RuntimeError('Caddy changed before activation; rerun')
            atomic_write(active, candidate, stat)
            changed = True
            command('docker', 'exec', container, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile')
            probe(args.api_host, args.north_origin, True)
            probe(args.api_host)
            print('AKIA_PORTAL_ROUTE=active_verified')
        except Exception:
            if changed:
                if active.read_bytes() != candidate:
                    raise RuntimeError('Concurrent Caddy modification; automatic overwrite refused, use recorded backup')
                atomic_write(active, original, stat)
                command('docker', 'exec', container, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile')
                command('docker', 'exec', container, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile')
                probe(args.api_host)
                print('AKIA_PORTAL_ROUTE=rolled_back_verified')
            raise
        finally:
            staging.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never include HTTP body, environment or rendered Caddy in diagnostics.
        print('AKIA_PORTAL_ROUTE=failed error_type=' + type(error).__name__)
        raise SystemExit(1)
