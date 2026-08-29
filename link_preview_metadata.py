"""Bounded HTML metadata decoding and extraction for link-preview workers."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
import unicodedata


MAXIMUM_DECODED_HTML_BYTES = 1024 * 1024
MAXIMUM_START_TAGS = 256
MAXIMUM_ATTRIBUTES = 32
MAXIMUM_ATTRIBUTE_BYTES = 8 * 1024
_CHARSETS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "windows-1252": "windows-1252",
    "cp1252": "windows-1252",
    "iso-8859-1": "windows-1252",
    "latin1": "windows-1252",
}
_BIDI_CONTROL = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_CONTROL = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]")
_WHITESPACE = re.compile(r"\s+")
_META_CHARSET = re.compile(
    br"<meta\s+[^>]*charset\s*=\s*(?:[\"']\s*)?([A-Za-z0-9._-]{1,40})",
    re.IGNORECASE,
)


class LinkPreviewMetadataError(ValueError):
    code = "link_preview.metadata_invalid"


@dataclass(frozen=True)
class LinkPreviewMetadata:
    title: str | None
    description: str | None
    site_name: str
    display_host: str
    image_candidate: str | None
    image_alt: str | None


def _content_type(value: str) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value or "\0" in value:
        raise LinkPreviewMetadataError("metadata content type invalid")
    parts = [part.strip() for part in value.split(";")]
    essence = parts[0].lower()
    if essence not in {"text/html", "application/xhtml+xml"}:
        raise LinkPreviewMetadataError("metadata content type unsupported")
    charset: str | None = None
    for parameter in parts[1:]:
        if not parameter:
            continue
        name, separator, raw = parameter.partition("=")
        if not separator or name.strip().lower() != "charset" or charset is not None:
            raise LinkPreviewMetadataError("metadata content type invalid")
        label = raw.strip().strip('"\'').lower()
        charset = _CHARSETS.get(label)
        if charset is None:
            raise LinkPreviewMetadataError("metadata charset unsupported")
    if essence == "application/xhtml+xml" and charset not in {None, "utf-8"}:
        raise LinkPreviewMetadataError("metadata charset unsupported")
    return essence, charset


def decode_html(body: bytes, content_type: str) -> str:
    """Decode one already transfer-decoded bounded HTML body."""

    if not isinstance(body, bytes) or len(body) > MAXIMUM_DECODED_HTML_BYTES:
        raise LinkPreviewMetadataError("metadata body invalid")
    essence, charset = _content_type(content_type)
    if body.startswith(b"\xef\xbb\xbf"):
        selected = "utf-8-sig"
    elif charset is not None:
        selected = charset
    elif essence == "application/xhtml+xml":
        selected = "utf-8"
    else:
        match = _META_CHARSET.search(body[:1024])
        if match:
            label = match.group(1).decode("ascii").lower()
            selected = _CHARSETS.get(label)
            if selected is None:
                raise LinkPreviewMetadataError("metadata charset unsupported")
        else:
            selected = "utf-8"
    errors = "replace" if selected == "utf-8" and charset is None and not body.startswith(b"\xef\xbb\xbf") else "strict"
    try:
        return body.decode(selected, errors=errors)
    except UnicodeDecodeError as exc:
        raise LinkPreviewMetadataError("metadata body invalid") from exc


def _text(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value)
    normalized = _BIDI_CONTROL.sub("", _CONTROL.sub("", normalized))
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    if not normalized:
        return None
    return "".join(list(normalized)[:maximum])


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.start_tags = 0
        self.stopped = False
        self.in_title = False
        self.title_parts: list[str] = []
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.stopped:
            return
        self.start_tags += 1
        if self.start_tags > MAXIMUM_START_TAGS or len(attrs) > MAXIMUM_ATTRIBUTES:
            raise LinkPreviewMetadataError("metadata structure invalid")
        for name, value in attrs:
            if len(name.encode("utf-8")) > MAXIMUM_ATTRIBUTE_BYTES or value is not None and len(value.encode("utf-8")) > MAXIMUM_ATTRIBUTE_BYTES:
                raise LinkPreviewMetadataError("metadata structure invalid")
        normalized_tag = tag.lower()
        if normalized_tag == "body":
            self.stopped = True
            return
        if normalized_tag == "title":
            self.in_title = True
            return
        if normalized_tag != "meta":
            return
        fields = {name.lower(): value for name, value in attrs if value is not None}
        content = fields.get("content")
        if content is None:
            return
        property_name = (fields.get("property") or "").strip().lower()
        ordinary_name = (fields.get("name") or "").strip().lower()
        key = property_name or ordinary_name
        allowed = {
            "og:title", "twitter:title", "og:description", "description",
            "twitter:description", "og:site_name", "og:image:secure_url",
            "og:image", "twitter:image", "og:image:alt",
        }
        if key in allowed and key not in self.values:
            self.values[key] = content

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self.in_title = False
        if normalized == "head":
            self.stopped = True

    def handle_data(self, data: str) -> None:
        if self.in_title and not self.stopped:
            self.title_parts.append(data)


def parse_metadata(html: str, *, display_host: str) -> LinkPreviewMetadata:
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAXIMUM_DECODED_HTML_BYTES:
        raise LinkPreviewMetadataError("metadata body invalid")
    host = _text(display_host, 253)
    if host is None or host != display_host:
        raise LinkPreviewMetadataError("metadata host invalid")
    parser = _Collector()
    try:
        parser.feed(html)
        parser.close()
    except (LinkPreviewMetadataError, RecursionError):
        raise
    except Exception as exc:
        raise LinkPreviewMetadataError("metadata structure invalid") from exc
    document_title = "".join(parser.title_parts)
    title = _text(
        parser.values.get("og:title")
        or document_title
        or parser.values.get("twitter:title"),
        200,
    )
    description = _text(
        parser.values.get("og:description")
        or parser.values.get("description")
        or parser.values.get("twitter:description"),
        500,
    )
    site_name = _text(parser.values.get("og:site_name"), 120) or host
    image_candidate = _text(
        parser.values.get("og:image:secure_url")
        or parser.values.get("og:image")
        or parser.values.get("twitter:image"),
        2_049,
    )
    if image_candidate is not None and len(image_candidate) > 2_048:
        image_candidate = None
    return LinkPreviewMetadata(
        title=title,
        description=description,
        site_name=site_name,
        display_host=host,
        image_candidate=image_candidate,
        image_alt=_text(parser.values.get("og:image:alt"), 200),
    )


__all__ = [
    "LinkPreviewMetadata",
    "LinkPreviewMetadataError",
    "decode_html",
    "parse_metadata",
]
