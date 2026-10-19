"""Pure restricted owner-setup ingress contract; no installation or activation."""

from __future__ import annotations

import json
from pathlib import Path

from .profile import NODE_UPSTREAM, canonical_caddy_host

SETUP_GET_PATHS = ('/auth/setup', '/auth/google/callback', '/auth/setup/complete')
SETUP_POST_PATHS = ('/auth/setup/start',)


def render_setup_caddyfile(host: str, *, certificate: Path | None = None, key: Path | None = None) -> str:
    """Render only fixed ceremony routes to the reserved loopback gateway.

    The later setup lifecycle must verify the pinned Caddy binary, canonical
    TLS configuration and exclusive stopped-server reservation before loading
    this configuration. Rendering grants no activation authority.
    """
    host = canonical_caddy_host(host)
    if (certificate is None) != (key is None):
        raise ValueError('Both TLS files are required')
    tls = ''
    if certificate is not None:
        for path in (certificate, key):
            if not path.is_absolute() or any(ord(value) < 32 or ord(value) == 127 for value in str(path)):
                raise ValueError('Unsafe TLS path')
        tls = f'tls {json.dumps(str(certificate))} {json.dumps(str(key))}'
    proxy = f'''reverse_proxy {NODE_UPSTREAM} {{
            header_up -Forwarded
            header_up -X-Real-IP
            header_up -X-Forwarded-For
            header_up -X-Forwarded-Port
            header_up Host {host}
            header_up X-Forwarded-Host {host}
            header_up X-Forwarded-Proto https
        }}'''
    return f'''# Owner setup only. Generated configuration is not activated.
{{
    admin 127.0.0.1:2019
    persist_config off
    grace_period 10s
    auto_https {'off' if tls else 'disable_redirects'}
    log {{
        output discard
    }}
    servers {{
        strict_sni_host on
        protocols h1 h2
        max_header_size 16KB
        timeouts {{
            read_header 5s
            read_body 10s
            write 30s
            idle 10s
        }}
    }}
}}

# Never redirect a callback query from cleartext HTTP.
http:// {{
    respond 404
}}

https://{host} {{
    {tls}
    log {{
        output discard
    }}
    header {{
        -Server
        Cache-Control "no-store"
        Referrer-Policy "no-referrer"
        X-Content-Type-Options "nosniff"
        Content-Security-Policy "default-src 'none'; form-action 'self' https://accounts.google.com; base-uri 'none'; frame-ancestors 'none'"
    }}
    request_body {{
        max_size 8KB
    }}
    @setup_page path /auth/setup
    header @setup_page {{
        defer
        Referrer-Policy "same-origin"
    }}
    @setup_get {{
        method GET
        path {' '.join(SETUP_GET_PATHS)}
    }}
    @setup_post {{
        method POST
        path {' '.join(SETUP_POST_PATHS)}
    }}
    handle @setup_get {{
        {proxy}
    }}
    handle @setup_post {{
        {proxy}
    }}
    handle {{
        respond 404
    }}
}}
'''
