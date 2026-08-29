"""Private stdio worker for hostile link-preview network and decode work."""

from __future__ import annotations

import base64
import json
import os
import sys
from urllib.parse import urljoin

from link_preview_image import LinkPreviewImageError, transform_image
from link_preview_metadata import LinkPreviewMetadataError, decode_html, parse_metadata
from link_preview_policy import LinkPreviewPolicyError, normalize_preview_url
from link_preview_transport import LinkPreviewTransportError, fetch_public_resource


MAXIMUM_REQUEST_BYTES = 4 * 1024
MAXIMUM_RESPONSE_BYTES = 1024 * 1024

for _environment_name in tuple(os.environ):
    if _environment_name not in {"LANG", "PYTHONUTF8", "SYSTEMROOT", "WINDIR"}:
        os.environ.pop(_environment_name, None)


def _write(payload: dict[str, object]) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(body) > MAXIMUM_RESPONSE_BYTES:
        body = b'{"code":"link_preview.unavailable","type":"error"}'
    sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()


def _phase(value: str) -> None:
    _write({"phase": value, "type": "phase"})


def _error_code(exc: Exception) -> str:
    if isinstance(exc, (LinkPreviewPolicyError, LinkPreviewTransportError)) and getattr(exc, "code", "") == "link_preview.blocked":
        return "link_preview.blocked"
    return "link_preview.unavailable"


def _page(url: str) -> dict[str, object]:
    normalized = normalize_preview_url(url)
    fetched = fetch_public_resource(normalized, kind="page", phase=_phase)
    _phase("parse")
    html = decode_html(fetched.body, fetched.content_type)
    metadata = parse_metadata(html, display_host=fetched.final_url.host)
    if metadata.title is None and metadata.description is None:
        return {"status": "unavailable"}
    image_candidate: str | None = None
    if metadata.image_candidate:
        try:
            image_candidate = normalize_preview_url(
                urljoin(fetched.final_url.canonical_url, metadata.image_candidate)
            ).canonical_url
        except LinkPreviewPolicyError:
            image_candidate = None
    result: dict[str, object] = {
        "cache_control": list(fetched.cache_control),
        "description": metadata.description,
        "display_host": metadata.display_host,
        "final_url": fetched.final_url.canonical_url,
        "image_alt": metadata.image_alt,
        "image_candidate": image_candidate,
        "site_name": metadata.site_name,
        "status": "ready",
        "title": metadata.title,
        "vary": list(fetched.vary),
    }
    return result


def _image(url: str) -> dict[str, object]:
    normalized = normalize_preview_url(url)
    fetched = fetch_public_resource(normalized, kind="image", phase=_phase)
    _phase("image_decode")
    mime = fetched.content_type.split(";", 1)[0].strip().lower()
    transformed = transform_image(fetched.body, mime)
    if transformed is None:
        return {"status": "unavailable"}
    return {
        "body": base64.b64encode(transformed).decode("ascii"),
        "final_url": fetched.final_url.canonical_url,
        "status": "ready",
    }


def _request(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != {"id", "kind", "url"}
        or not isinstance(value.get("id"), str)
        or not 1 <= len(value["id"]) <= 64
        or value.get("kind") not in {"page", "image"}
        or not isinstance(value.get("url"), str)
        or not 1 <= len(value["url"].encode("utf-8")) <= 2_048
    ):
        raise ValueError("request invalid")
    request_id = value["id"]
    try:
        result = _page(value["url"]) if value["kind"] == "page" else _image(value["url"])
        return {"id": request_id, "result": result, "type": "result"}
    except (LinkPreviewPolicyError, LinkPreviewTransportError, LinkPreviewMetadataError, LinkPreviewImageError, OSError, ValueError) as exc:
        return {"code": _error_code(exc), "id": request_id, "type": "error"}


def main() -> int:
    while True:
        line = sys.stdin.buffer.readline(MAXIMUM_REQUEST_BYTES + 1)
        if not line:
            return 0
        if len(line) > MAXIMUM_REQUEST_BYTES or not line.endswith(b"\n"):
            _write({"code": "link_preview.unavailable", "type": "error"})
            return 1
        try:
            value = json.loads(line.decode("utf-8"))
            response = _request(value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            _write({"code": "link_preview.unavailable", "type": "error"})
            return 1
        _write(response)


if __name__ == "__main__":
    raise SystemExit(main())
