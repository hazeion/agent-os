"""Foreground Linux-only setup gateway lifecycle; never starts the dashboard."""

from __future__ import annotations

import http.client
import os
from pathlib import Path
import secrets
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time

from deploy.caddy.profile import caddy_subprocess_environment, validate_owned_path, verify_downloaded_release, verify_signed_checksums
from deploy.caddy.setup_profile import render_setup_caddyfile
from mentat.owner_setup_bridge import SetupBridge
from mentat.web_runtime import find_node_24, node_environment


class SetupRuntimeError(RuntimeError):
    pass


def gateway_script() -> Path:
    source = Path(__file__).resolve().parents[1] / 'web' / 'scripts' / 'owner-setup-gateway.mjs'
    installed = Path(sys.prefix) / 'share' / 'mentat' / 'setup' / 'owner-setup-gateway.mjs'
    for candidate in (source, installed):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise SetupRuntimeError('Setup gateway is not installed')


from .owner_setup_guard import stop_guard as _stop


class OwnerSetupRuntime:
    def __init__(self, *, host: str, caddy: Path, cosign: Path, release_dir: Path,
                 architecture: str, certificate: Path, key: Path):
        if sys.platform != 'linux' or getattr(sys, 'frozen', False):
            raise SetupRuntimeError('Google owner setup requires installed Python on Linux')
        self.node = find_node_24()
        if self.node is None:
            raise SetupRuntimeError('Supported Node runtime is required')
        for path in (caddy, cosign, certificate, key):
            owner = path.lstat().st_uid
            if owner not in {0, os.geteuid()}:
                raise SetupRuntimeError('Setup files must belong to the operator or root')
            validate_owned_path(path, expected_uid=owner, directory=False)
        if key.stat().st_mode & 0o077:
            raise SetupRuntimeError('TLS private key requires owner-only permissions')
        verify_signed_checksums(release_dir, cosign)
        verify_downloaded_release(release_dir, architecture, caddy_binary=caddy)
        # Load the supplied chain/key before reserving any public listener.
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(certificate, key)
        self.script = gateway_script()
        self.caddy, self.host = caddy, host
        self.config = render_setup_caddyfile(host, certificate=certificate, key=key)
        self.bridge = self.thread = self.node_process = self.caddy_process = None
        self.temporary = None
        self.instance = secrets.token_urlsafe(32)

    def _alive(self):
        return self.node_process is not None and self.node_process.poll() is None and (self.caddy_process is None or self.caddy_process.poll() is None)

    def _launch(self, kind, binary, resource, environment):
        guard = Path(__file__).with_name('owner_setup_guard.py')
        return subprocess.Popen([sys.executable, '-I', str(guard), '--parent-pid', str(os.getpid()),
            '--kind', kind, '--binary', str(binary), '--resource', str(resource)], env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def start(self, ceremony):
        token = secrets.token_urlsafe(32)
        self.bridge = SetupBridge(ceremony, token)
        self.thread = threading.Thread(target=self.bridge.serve_forever, daemon=True)
        self.thread.start()
        try:
            environment = node_environment(token=token, bridge_port=self.bridge.server_port, gateway_port=8888, gateway_host='127.0.0.1')
            environment.update(MENTAT_SETUP_ORIGIN='https://' + self.host,
                MENTAT_SETUP_BRIDGE=f'http://127.0.0.1:{self.bridge.server_port}', MENTAT_SETUP_TOKEN=token,
                MENTAT_SETUP_PORT='8888', MENTAT_SETUP_INSTANCE=self.instance)
            self.node_process = self._launch('node', self.node, self.script, environment)
            self._wait_ready(tls=False)
            self.temporary = tempfile.TemporaryDirectory(prefix='mentat-owner-setup-')
            root = Path(self.temporary.name)
            config = root / 'Caddyfile'
            config.write_text(self.config, encoding='utf-8')
            config.chmod(0o600)
            environment = caddy_subprocess_environment(root)
            checked = subprocess.run([str(self.caddy), 'adapt', '--validate', '--config', str(config), '--adapter', 'caddyfile'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment, timeout=20)
            if checked.returncode:
                raise SetupRuntimeError('Setup TLS configuration failed validation')
            self.caddy_process = self._launch('caddy', self.caddy, config, environment)
            self._wait_ready(tls=True)
        except BaseException:
            self.stop()
            raise

    def _wait_ready(self, *, tls):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not self._alive():
                raise SetupRuntimeError('Setup gateway exited before readiness')
            connection = None
            try:
                if tls:
                    connection = http.client.HTTPSConnection(self.host, 443, timeout=2, context=ssl.create_default_context())
                    headers = {}
                else:
                    connection = http.client.HTTPConnection('127.0.0.1', 8888, timeout=2)
                    headers = {'Host': self.host, 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': self.host}
                connection.request('GET', '/auth/setup', headers=headers)
                response = connection.getresponse()
                body = response.read(8193)
                if response.status == 200 and len(body) <= 8192 and self.instance.encode() in body:
                    return
            except (OSError, http.client.HTTPException):
                pass
            finally:
                if connection:
                    connection.close()
            time.sleep(0.05)
        raise SetupRuntimeError('Canonical HTTPS setup readiness could not be verified')

    def stop(self) -> bool:
        # Withdraw TLS ingress before the browser gateway and private authority.
        caddy_stopped = _stop(self.caddy_process)
        node_stopped = _stop(self.node_process)
        if self.bridge is not None:
            self.bridge.shutdown()
            self.bridge.server_close()
            self.thread.join(5)
        stopped = caddy_stopped and node_stopped and (self.thread is None or not self.thread.is_alive())
        if stopped and self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        return stopped
