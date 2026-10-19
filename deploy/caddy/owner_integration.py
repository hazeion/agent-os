"""Real-Caddy owner ingress gate. Application authentication is tested by Next."""

from pathlib import Path
import subprocess
import tempfile
import time

from .disposable_integration import DisposableIntegrationError, SPOOFED_HEADERS, _free_port, _start_backend, _stop_backend, request_http, assert_loopback_listener_inventory
from .owner_profile import render_owner_caddyfile
from .profile import caddy_subprocess_environment


def run_owner_integration(*, caddy: Path, certificate: Path, key: Path, host: str):
    ports = []
    while len(ports) < 4:
        value = _free_port()
        if value not in ports: ports.append(value)
    http_port, https_port, admin_port, upstream_port = ports
    rendered = render_owner_caddyfile(host, certificate=certificate, key=key)
    rendered = rendered.replace('admin 127.0.0.1:2019', f'admin 127.0.0.1:{admin_port}\n    default_bind 127.0.0.1\n    http_port {http_port}\n    https_port {https_port}')
    rendered = rendered.replace('reverse_proxy 127.0.0.1:8888', f'reverse_proxy 127.0.0.1:{upstream_port}')
    backend = _start_backend(upstream_port)
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='mentat-owner-tls-') as temporary:
            root = Path(temporary)
            config = root / 'Caddyfile'
            config.write_text(rendered, encoding='utf-8')
            env = caddy_subprocess_environment(root)
            checked = subprocess.run([str(caddy), 'adapt', '--validate', '--config', str(config), '--adapter', 'caddyfile'], env=env, capture_output=True, timeout=20)
            if checked.returncode: raise DisposableIntegrationError('Owner ingress parser gate failed')
            process = subprocess.Popen([str(caddy), 'run', '--config', str(config), '--adapter', 'caddyfile'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 10
            spoofed = {**SPOOFED_HEADERS, 'X-Middleware-Subrequest': 'middleware', 'X-Mentat-Owner-Session': 'forged', 'X-Mentat-Bridge-Token': 'forged', 'X-Mentat-Csrf': 'browser-csrf'}
            while True:
                if process.poll() is not None: raise DisposableIntegrationError('Owner ingress exited')
                try:
                    result = request_http(https_port, host, '/sign-in', secure=True, trust_certificate=certificate, extra_headers=spoofed)
                    if result[0] == 200: break
                except OSError: pass
                if time.monotonic() >= deadline: raise DisposableIntegrationError('Owner ingress readiness failed')
                time.sleep(0.05)
            observed = backend.captures[-1]
            if observed.get('host') != host or observed.get('x-forwarded-host') != host or observed.get('x-forwarded-proto') != 'https':
                raise DisposableIntegrationError('Owner canonical proxy fields failed')
            if any(name in observed for name in ('forwarded', 'x-real-ip', 'x-forwarded-for', 'x-forwarded-port', 'x-middleware-subrequest', 'x-mentat-owner-session', 'x-mentat-bridge-token')):
                raise DisposableIntegrationError('Owner ingress retained untrusted authority headers')
            if observed.get('x-mentat-csrf') != 'browser-csrf' or result[1].get('referrer-policy') != 'same-origin':
                raise DisposableIntegrationError('Owner form policy failed')
            callback = request_http(https_port, host, '/auth/google/callback?code=synthetic', secure=True, trust_certificate=certificate)
            if callback[1].get('referrer-policy') != 'no-referrer': raise DisposableIntegrationError('Callback referrer policy failed')
            if request_http(http_port, host, '/auth/google/callback?code=synthetic')[0] != 404: raise DisposableIntegrationError('Cleartext callback was accepted')
            assert_loopback_listener_inventory((http_port, https_port, admin_port), caddy_pid=process.pid)
    finally:
        if process:
            process.terminate()
            try: process.wait(12)
            except subprocess.TimeoutExpired: process.kill(); process.wait(3)
        _stop_backend(backend)
