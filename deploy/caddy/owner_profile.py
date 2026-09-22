"""Ordinary owner website HTTPS ingress; activation belongs to the host CLI."""

from pathlib import Path
from .setup_profile import render_setup_caddyfile


def render_owner_caddyfile(host: str, *, certificate: Path, key: Path) -> str:
    # Keep the already-qualified TLS, logging, header and timeout contract.
    setup = render_setup_caddyfile(host, certificate=certificate, key=key)
    setup = setup.replace('@setup_page path /auth/setup', '@setup_page path /sign-in')
    # The ordinary dashboard owns bounded attachment uploads behind owner/CSRF
    # admission. Its exact route manifest, not Caddy, classifies application paths.
    setup = setup.replace('max_size 8KB', 'max_size 32MB')
    setup = setup.replace('read_body 10s', 'read_body 30s').replace('write 30s', 'write 240s')
    # Next owns nonce-bearing document CSP. The setup-only default-src:none
    # policy would otherwise prevent the authenticated application from loading.
    setup = '\n'.join(line for line in setup.split('\n') if 'Content-Security-Policy ' not in line)
    start = setup.index('    @setup_get {')
    proxy_start = setup.index('reverse_proxy ', start)
    proxy_end = setup.index('\n        }', proxy_start) + len('\n        }')
    proxy = setup[proxy_start:proxy_end]
    proxy = proxy.replace('header_up -Forwarded', '''header_up -X-Middleware-*
            header_up -X-Mentat-Bridge-Token
            header_up -X-Mentat-Owner-Session
            header_up -X-Mentat-Owner-Csrf
            header_up -X-Mentat-Owner-Lease
            header_up -X-Mentat-Setup-Token
            header_up -Forwarded''')
    # Extract the fixed upstream stanza, remove setup-only matchers, and retain
    # Node's exhaustive authenticated route inventory as the application gate.
    return (setup[:start] + '    ' + proxy + '\n}\n').replace('# Owner setup only. Generated configuration is not activated.', '# Owner website. Authenticated application admission is enforced by Node and Python.')
