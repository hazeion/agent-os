"""Explicit verified-Caddy setup ingress test on disposable loopback ports."""

from pathlib import Path
import subprocess
import tempfile
import time

from .disposable_integration import (
    DisposableIntegrationError, SPOOFED_HEADERS, _free_port, _start_backend,
    _stop_backend, request_http, assert_loopback_listener_inventory,
)
from .profile import caddy_subprocess_environment
from .setup_profile import render_setup_caddyfile


def run_setup_integration(*, caddy: Path, certificate: Path, key: Path, host: str):
    ports = []
    while len(ports) < 4:
        port = _free_port()
        if port not in ports:
            ports.append(port)
    http_port, https_port, admin_port, upstream_port = ports
    rendered = render_setup_caddyfile(host, certificate=certificate, key=key)
    # Only listener addresses/ports differ from the actual setup contract.
    rendered = rendered.replace('admin 127.0.0.1:2019', f'admin 127.0.0.1:{admin_port}\n    default_bind 127.0.0.1\n    http_port {http_port}\n    https_port {https_port}')
    rendered = rendered.replace('reverse_proxy 127.0.0.1:8888', f'reverse_proxy 127.0.0.1:{upstream_port}')
    backend = _start_backend(upstream_port)
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='mentat-setup-tls-') as temporary:
            root = Path(temporary)
            config = root / 'Caddyfile'
            config.write_text(rendered, encoding='utf-8')
            environment = caddy_subprocess_environment(root)
            checked = subprocess.run([str(caddy), 'adapt', '--validate', '--config', str(config), '--adapter', 'caddyfile'], env=environment, capture_output=True, timeout=20)
            if checked.returncode:
                raise DisposableIntegrationError('Setup Caddyfile failed actual parser validation')
            process = subprocess.Popen([str(caddy), 'run', '--config', str(config), '--adapter', 'caddyfile'], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise DisposableIntegrationError('Setup Caddy exited before readiness')
                try:
                    result = request_http(https_port, host, '/auth/setup', secure=True, trust_certificate=certificate, extra_headers=SPOOFED_HEADERS)
                    if result[0] == 200:
                        break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise DisposableIntegrationError('Setup TLS did not become ready')
                time.sleep(0.05)
            captured = backend.captures[-1]
            if captured.get('host') != host or captured.get('x-forwarded-host') != host or captured.get('x-forwarded-proto') != 'https' or any(name in captured for name in ('forwarded', 'x-real-ip', 'x-forwarded-for', 'x-forwarded-port')):
                raise DisposableIntegrationError('Setup proxy headers do not match gateway contract')
            if result[1].get('cache-control') != 'no-store' or result[1].get('referrer-policy') != 'same-origin':
                raise DisposableIntegrationError('Setup security headers missing')
            callback = request_http(https_port, host, '/auth/google/callback?code=synthetic-private-code', secure=True, trust_certificate=certificate)
            if callback[1].get('referrer-policy') != 'no-referrer':
                raise DisposableIntegrationError('Setup callback referrer policy is unsafe')
            for path in ('/', '/api/tasks', '/bridge/v1/tasks', '/auth/setup/start'):
                before = len(backend.captures)
                denied = request_http(https_port, host, path, secure=True, trust_certificate=certificate)
                if denied[0] != 404 or len(backend.captures) != before:
                    raise DisposableIntegrationError('Setup route exposed unrelated capabilities')
            cleartext = request_http(http_port, host, '/auth/google/callback?code=synthetic-private-code')
            if cleartext[0] != 404 or 'location' in cleartext[1]:
                raise DisposableIntegrationError('Cleartext setup callback redirected')
            assert_loopback_listener_inventory((http_port, https_port, admin_port), caddy_pid=process.pid)
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(3)
        _stop_backend(backend)
