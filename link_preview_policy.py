"""Pure URL, IDNA, special-use name, and public-address policy for link previews.

This module performs no DNS or network I/O.  Callers supply resolver answers to
``validate_public_addresses`` and receive only canonical numeric candidates.
Raw URLs and addresses are deliberately absent from exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Iterable
from urllib.parse import quote, unquote_to_bytes, urlsplit

import idna


MAXIMUM_URL_BYTES = 2_048
MAXIMUM_DNS_ANSWERS = 16

_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_ENCODED_BACKSLASH = re.compile(r"%5c", re.IGNORECASE)
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_CANONICAL_IPV4 = re.compile(
    r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}\Z"
)
_NUMERIC_IPV4_LIKE = re.compile(r"[0-9.]+\Z")
_HEX_IPV4_LIKE = re.compile(r"(?:0[xX][0-9A-Fa-f]+|[0-9A-Fa-f]+)(?:\.(?:0[xX][0-9A-Fa-f]+|[0-9A-Fa-f]+))*\Z")

_SECRET_QUERY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "password",
        "secret",
        "sig",
        "signature",
        "x-amz-signature",
        "x-goog-signature",
    }
)

_SPECIAL_USE_NAMES = frozenset(
    {
        "localhost",
        "local",
        "home.arpa",
        "test",
        "invalid",
        "example",
        "example.com",
        "example.net",
        "example.org",
    }
)

# Reviewed conservative deny tables derived from the IANA IPv4 and IPv6
# special-purpose registries.  ``ipaddress.is_global`` is required as a second,
# independent check below.  Broad containing prefixes intentionally fail closed
# when a special-purpose block has narrow globally-reachable exceptions.
_IPV4_DENY = tuple(
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_IPV6_DENY = tuple(
    ipaddress.ip_network(value)
    for value in (
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2002::/16",
        "3fff::/20",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)
_IPV4_GLOBAL_EXCEPTIONS = frozenset(
    {ipaddress.ip_address("192.0.0.9"), ipaddress.ip_address("192.0.0.10")}
)
_IPV6_GLOBAL_EXCEPTIONS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "2001:1::1/128",
        "2001:1::2/128",
        "2001:1::3/128",
        "2001:3::/32",
        "2001:4:112::/48",
        "2001:20::/28",
        "2001:30::/28",
    )
)


class LinkPreviewPolicyError(ValueError):
    """A fixed policy result that never contains the rejected input."""

    def __init__(self, code: str):
        safe_code = (
            code
            if re.fullmatch(r"link_preview\.[a-z0-9_]+", code)
            else "link_preview.invalid"
        )
        super().__init__(safe_code)
        self.code = safe_code


@dataclass(frozen=True)
class NormalizedPreviewURL:
    canonical_url: str
    host: str
    request_target: str
    is_ip_literal: bool


@dataclass(frozen=True)
class PublicAddressSet:
    addresses: tuple[str, ...]
    connection_candidates: tuple[str, ...]


def _fail(code: str = "link_preview.invalid") -> None:
    raise LinkPreviewPolicyError(code)


def _normalize_percent_encoding(value: str) -> str:
    if _BAD_PERCENT.search(value):
        _fail()
    output: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "%":
            output.append(value[index])
            index += 1
            continue
        byte = int(value[index + 1 : index + 3], 16)
        character = chr(byte)
        output.append(character if character in _UNRESERVED else f"%{byte:02X}")
        index += 3
    return "".join(output)


def _remove_dot_segments(path: str) -> str:
    source = path
    output = ""
    while source:
        if source.startswith("../"):
            source = source[3:]
        elif source.startswith("./"):
            source = source[2:]
        elif source.startswith("/./"):
            source = "/" + source[3:]
        elif source == "/.":
            source = "/"
        elif source.startswith("/../"):
            source = "/" + source[4:]
            output = output.rsplit("/", 1)[0]
        elif source == "/..":
            source = "/"
            output = output.rsplit("/", 1)[0]
        elif source in {".", ".."}:
            source = ""
        else:
            boundary = source.find("/", 1 if source.startswith("/") else 0)
            if boundary < 0:
                output += source
                source = ""
            else:
                output += source[:boundary]
                source = source[boundary:]
    return output or "/"


def _query_contains_secret(query: str) -> bool:
    for field in re.split(r"[&;]", query):
        name = field.split("=", 1)[0]
        try:
            decoded = unquote_to_bytes(name).decode("ascii").casefold()
        except (UnicodeDecodeError, ValueError):
            continue
        if decoded in _SECRET_QUERY_NAMES:
            return True
    return False


def _is_special_use_name(host: str) -> bool:
    return any(host == name or host.endswith("." + name) for name in _SPECIAL_USE_NAMES)


def _normalize_dns_host(host: str) -> str:
    host = host.translate(str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."}))
    if host.endswith(".."):
        _fail()
    host = host[:-1] if host.endswith(".") else host
    if not host or len(host) > 253:
        _fail()
    labels: list[str] = []
    for raw_label in host.split("."):
        if not raw_label:
            _fail()
        try:
            label = idna.encode(
                raw_label,
                uts46=True,
                transitional=False,
                std3_rules=True,
            ).decode("ascii").lower()
        except idna.IDNAError:
            _fail()
        if len(label) > 63 or not _DNS_LABEL.fullmatch(label):
            _fail()
        labels.append(label)
    normalized = ".".join(labels)
    # UTS #46 can map non-ASCII digits and separators into an IPv4-looking
    # hostname.  Re-run the literal/ambiguity gate after mapping so the system
    # resolver never gets a second chance to interpret a disguised numeric form.
    if _normalize_ip_literal(normalized) is not None:
        _fail()
    if len(normalized) > 253 or _is_special_use_name(normalized):
        _fail("link_preview.blocked")
    return normalized


def _address_is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id is not None or address.sixtofour is not None or address.teredo is not None:
            return False
        mapped = address.ipv4_mapped
        if mapped is not None:
            return _address_is_public(mapped)
        if any(address in network for network in _IPV6_GLOBAL_EXCEPTIONS):
            return bool(address.is_global)
        if any(address in network for network in _IPV6_DENY):
            return False
    elif address not in _IPV4_GLOBAL_EXCEPTIONS:
        if any(address in network for network in _IPV4_DENY):
            return False
    return bool(address.is_global)


def _normalize_ip_literal(host: str) -> tuple[str, bool] | None:
    if "%" in host:
        _fail()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if _NUMERIC_IPV4_LIKE.fullmatch(host) or (
            _HEX_IPV4_LIKE.fullmatch(host) and any(character.isdigit() for character in host)
        ):
            _fail()
        return None
    canonical = address.compressed
    if isinstance(address, ipaddress.IPv4Address):
        if not _CANONICAL_IPV4.fullmatch(host) or host != canonical:
            _fail()
    elif host != canonical:
        _fail()
    if not _address_is_public(address):
        _fail("link_preview.blocked")
    return canonical, True


def normalize_preview_url(raw_url: str) -> NormalizedPreviewURL:
    """Return one canonical public-HTTPS candidate without resolving DNS."""

    if (
        not isinstance(raw_url, str)
        or not raw_url
        or raw_url != raw_url.strip()
        or raw_url.startswith("//")
        or "\\" in raw_url
        or _ENCODED_BACKSLASH.search(raw_url)
        or _CONTROL_OR_SPACE.search(raw_url)
        or _BAD_PERCENT.search(raw_url)
    ):
        _fail()
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
        host = parsed.hostname
    except (TypeError, ValueError):
        _fail()
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        _fail("link_preview.unsupported")

    literal = _normalize_ip_literal(host)
    if literal is None:
        normalized_host = _normalize_dns_host(host)
        serialized_host = normalized_host
        is_ip_literal = False
    else:
        normalized_host, is_ip_literal = literal
        serialized_host = (
            f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        )

    path = _remove_dot_segments(_normalize_percent_encoding(parsed.path or "/"))
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    query = _normalize_percent_encoding(parsed.query)
    if _query_contains_secret(query):
        _fail("link_preview.blocked")
    query = quote(query, safe="/?%:@!$&'()*+,;=-._~")
    request_target = path + ("?" + query if query else "")
    canonical = f"https://{serialized_host}{request_target}"
    try:
        encoded = canonical.encode("ascii")
    except UnicodeEncodeError:
        _fail()
    if len(encoded) > MAXIMUM_URL_BYTES:
        _fail()
    return NormalizedPreviewURL(
        canonical_url=canonical,
        host=normalized_host,
        request_target=request_target,
        is_ip_literal=is_ip_literal,
    )


def validate_public_addresses(values: Iterable[str]) -> PublicAddressSet:
    """Validate one complete supplied A/AAAA answer set without DNS I/O."""

    if isinstance(values, (str, bytes)):
        _fail()
    normalized: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    try:
        candidates = list(values)
    except TypeError:
        _fail()
    for value in candidates:
        if not isinstance(value, str) or "%" in value:
            _fail()
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            _fail()
        if str(address) != value.lower():
            _fail()
        if not _address_is_public(address):
            _fail("link_preview.blocked")
        mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
        retained = mapped or address
        key = retained.compressed
        if key not in seen:
            seen.add(key)
            normalized.append(retained)
    if not normalized:
        _fail("link_preview.unavailable")
    if len(normalized) > MAXIMUM_DNS_ANSWERS:
        _fail("link_preview.answer_limit")
    first_v6 = next(
        (address.compressed for address in normalized if isinstance(address, ipaddress.IPv6Address)),
        None,
    )
    first_v4 = next(
        (address.compressed for address in normalized if isinstance(address, ipaddress.IPv4Address)),
        None,
    )
    return PublicAddressSet(
        addresses=tuple(address.compressed for address in normalized),
        connection_candidates=tuple(
            value for value in (first_v6, first_v4) if value is not None
        ),
    )


__all__ = [
    "LinkPreviewPolicyError",
    "MAXIMUM_DNS_ANSWERS",
    "MAXIMUM_URL_BYTES",
    "NormalizedPreviewURL",
    "PublicAddressSet",
    "normalize_preview_url",
    "validate_public_addresses",
]
