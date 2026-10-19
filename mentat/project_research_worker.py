"""Fixed credential-free public-page worker; no Model, Project or Run inputs."""
from __future__ import annotations

import os
import sys

for _name in tuple(os.environ):
    if _name not in {"LANG", "PYTHONUTF8", "SYSTEMROOT", "WINDIR"}:
        os.environ.pop(_name, None)
sys.dont_write_bytecode = True

import json
import re

from link_preview_policy import LinkPreviewPolicyError, normalize_preview_url
from link_preview_transport import LinkPreviewTransportError, fetch_public_research_page
from mentat.project_research_page import extract_page

MAX_LINE = 256 * 1024


def _write(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_LINE:
        raw = b'{"type":"error","code":"link_preview.unavailable"}'
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def main():
    if sys.platform != "linux":
        return 1
    import resource
    for name, maximum in ((resource.RLIMIT_AS, 256 * 1024 * 1024), (resource.RLIMIT_CPU, 10),
                          (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
        _, hard = resource.getrlimit(name)
        bound = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        resource.setrlimit(name, (bound, bound))
    while True:
        line = sys.stdin.buffer.readline(4097)
        if not line:
            return 0
        identifier = None
        try:
            if len(line) > 4096 or not line.endswith(b"\n"):
                raise ValueError()
            request = json.loads(line, object_pairs_hook=_pairs)
            if (not isinstance(request, dict) or set(request) != {"id", "kind", "url"}
                    or request["kind"] != "research_page" or not isinstance(request["id"], str)
                    or re.fullmatch(r"[0-9a-f]{32}", request["id"]) is None):
                raise ValueError()
            identifier = request["id"]
            normalized = normalize_preview_url(request["url"])
            fetched = fetch_public_research_page(normalized,
                        phase=lambda phase: _write({"type": "phase", "phase": phase}))
            _write({"type": "phase", "phase": "parse"})
            result = extract_page(fetched.body, fetched.content_type, fetched.final_url.canonical_url)
            _write({"type": "result", "id": identifier, "result": result})
        except (ValueError, TypeError, UnicodeError, OSError, RuntimeError, RecursionError) as error:
            code = "link_preview.blocked" if isinstance(error, (LinkPreviewPolicyError, LinkPreviewTransportError)) and getattr(error, "code", "") == "link_preview.blocked" else "link_preview.unavailable"
            _write({"type": "error", "id": identifier, "code": code})
            if identifier is None:
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
