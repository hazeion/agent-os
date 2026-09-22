"""Explicit foreground owner website. Local startup remains a separate mode."""

import http.client
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time

from deploy.caddy.owner_profile import render_owner_caddyfile
from deploy.caddy.profile import caddy_subprocess_environment
from .owner_setup_runtime import OwnerSetupRuntime, SetupRuntimeError


class OwnerWebsiteRuntime(OwnerSetupRuntime):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = render_owner_caddyfile(kwargs['host'], certificate=kwargs['certificate'], key=kwargs['key'])

    def start_website(self, data_root, runtime_environment):
        environment = os.environ.copy()
        environment.update(runtime_environment)
        environment.update(MENTAT_DATA_DIR=str(data_root), MENTAT_OWNER_ORIGIN='https://' + self.host,
            MENTAT_GATEWAY_INSTANCE=self.instance)
        self.node_process = self._launch('node', sys.executable, Path(__file__).with_name('owner_website_worker.py'), environment)
        try:
            self._wait_website(tls=False)
            self.temporary = tempfile.TemporaryDirectory(prefix='mentat-owner-website-')
            root = Path(self.temporary.name)
            config = root / 'Caddyfile'
            config.write_text(self.config, encoding='utf-8')
            config.chmod(0o600)
            environment = caddy_subprocess_environment(root)
            checked = subprocess.run([str(self.caddy), 'adapt', '--validate', '--config', str(config), '--adapter', 'caddyfile'],
                env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if checked.returncode:
                raise SetupRuntimeError('Owner website TLS configuration is invalid')
            self.caddy_process = self._launch('caddy', self.caddy, config, environment)
            self._wait_website(tls=True)
        except BaseException:
            self.stop()
            raise

    def _wait_website(self, *, tls):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not self._alive():
                raise SetupRuntimeError('Owner website exited before readiness')
            connection = None
            try:
                if tls:
                    connection = http.client.HTTPSConnection(self.host, 443, timeout=2, context=ssl.create_default_context())
                    path = '/sign-in'
                else:
                    connection = http.client.HTTPConnection('127.0.0.1', 8888, timeout=2)
                    path = '/api/gateway/health'
                connection.request('GET', path)
                response = connection.getresponse()
                body = response.read(65537)
                if response.status == 200 and len(body) <= 65536 and (not tls or self.instance.encode() in body):
                    return
            except (OSError, http.client.HTTPException):
                pass
            finally:
                if connection:
                    connection.close()
            time.sleep(0.05)
        raise SetupRuntimeError('Owner website HTTPS readiness could not be verified')
