"""One fixed Google HTTPS operation in a short-lived, private worker."""

from __future__ import annotations

import json
import os
import re
import sys
import threading

import requests

from owner_auth_google import CALLBACK_PATH, MAX_JWKS_BYTES, MAX_TOKEN_BYTES, _client_id, _json_object, _public_key, _secret
from owner_auth_webauthn import canonical_origin

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
MAX_INPUT_BYTES = 32 * 1024
MAX_OUTPUT_BYTES = MAX_JWKS_BYTES + 4096
MAX_TOKEN_RESPONSE_BYTES = 64 * 1024
MAX_CACHE_SECONDS = 3600
WORK_SECONDS = 10


def _opaque(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(not 33 <= ord(character) <= 126 for character in value):
        raise ValueError("invalid")
    return value


def _cache_seconds(headers) -> int:
    directives = [value.strip().lower() for value in headers.get("Cache-Control", "").split(",")]
    if any(value.split("=", 1)[0] in {"no-store", "no-cache"} for value in directives):
        return 0
    ages = []
    for value in directives:
        match = re.fullmatch(r'max-age="?([0-9]{1,10})"?', value)
        if match:
            ages.append(int(match[1]))
    age = headers.get("Age", "0")
    if not ages or not re.fullmatch(r"[0-9]{1,10}", age):
        return 0
    return max(0, min(MAX_CACHE_SECONDS, min(ages) - int(age)))


def _response_json(response, maximum: int) -> dict:
    if response.status_code != 200 or len(response.headers) > 64 or sum(len(str(k)) + len(str(v)) for k, v in response.headers.items()) > 16 * 1024:
        raise ValueError("unavailable")
    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json" or response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise ValueError("invalid")
    declared = response.headers.get("Content-Length")
    if declared is not None and (not re.fullmatch(r"[0-9]{1,6}", declared) or int(declared) > maximum):
        raise ValueError("invalid")
    content = bytearray()
    for chunk in response.iter_content(chunk_size=4096):
        if not isinstance(chunk, bytes) or len(content) + len(chunk) > maximum:
            raise ValueError("invalid")
        content.extend(chunk)
    if declared is not None and len(content) != int(declared):
        raise ValueError("invalid")
    return _json_object(bytes(content), maximum)


def perform(payload: dict) -> dict:
    """Private worker protocol; no endpoint, header or command can be supplied."""
    if payload == {"operation": "keys"}:
        method, endpoint, body, maximum = "GET", JWKS_ENDPOINT, None, MAX_JWKS_BYTES
    elif isinstance(payload, dict) and set(payload) == {"operation", "client_id", "origin", "code", "code_verifier", "client_secret"} and payload.get("operation") == "exchange":
        origin, hostname = canonical_origin(payload["origin"])
        if "." not in hostname or not any(character.isalpha() for character in hostname.rsplit(".", 1)[-1]):
            raise ValueError("invalid")
        body = {
            "grant_type": "authorization_code",
            "client_id": _client_id(payload["client_id"]),
            "redirect_uri": origin + CALLBACK_PATH,
            "code": _opaque(payload["code"], 4096),
            "code_verifier": _secret(payload["code_verifier"]),
            "client_secret": _opaque(payload["client_secret"], 4096),
        }
        method, endpoint, maximum = "POST", TOKEN_ENDPOINT, MAX_TOKEN_RESPONSE_BYTES
    else:
        raise ValueError("invalid")
    with requests.Session() as session:
        session.trust_env = False
        session.verify = True
        session.headers.clear()
        session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        with session.request(method, endpoint, data=body, headers={"Accept": "application/json", "Accept-Encoding": "identity"}, allow_redirects=False, stream=True, timeout=(3, 3)) as response:
            value = _response_json(response, maximum)
            if method == "POST":
                token = _opaque(value.get("id_token"), MAX_TOKEN_BYTES)
                return {"ok": True, "id_token": token}
            keys = value.get("keys")
            if not isinstance(keys, list) or not keys or not isinstance(keys[0], dict):
                raise ValueError("invalid")
            serialized = json.dumps(value, separators=(",", ":")).encode()
            _public_key(serialized, keys[0].get("kid"))
            return {"ok": True, "jwks": value, "max_age": _cache_seconds(response.headers)}


def main() -> int:
    # Independent watchdog also expires provider work if the parent disappears.
    watchdog = threading.Timer(WORK_SECONDS, lambda: os._exit(2))
    watchdog.daemon = True
    watchdog.start()
    try:
        payload = _json_object(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1), MAX_INPUT_BYTES)
        result = perform(payload)
        encoded = json.dumps(result, separators=(",", ":")).encode()
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise ValueError("invalid")
    except Exception:
        encoded = b'{"ok":false,"error":"unavailable"}'
    try:
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 0
    except (OSError, BrokenPipeError):
        return 2
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
