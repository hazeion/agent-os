"""Bounded untrusted public-page text, never a prompt or execution authority."""
from __future__ import annotations

from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin

from link_preview_metadata import decode_research_text
from link_preview_policy import LinkPreviewPolicyError, normalize_preview_url

MAX_TEXT = 64 * 1024
MAX_LINKS = 32
MAX_TAGS = 32_768
MAX_DEPTH = 128
_SKIP = frozenset({"script", "style", "template", "noscript", "iframe", "object", "embed",
                   "svg", "math", "form", "nav", "header", "footer", "aside"})
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "param", "source", "track", "wbr"})
_BLOCK = frozenset({"p", "div", "section", "article", "main", "li", "ul", "ol", "table", "tr",
                    "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr"})
_UNSAFE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


class ResearchPageError(ValueError):
    pass


def _fail():
    raise ResearchPageError("project_research.invalid_page")


def _clean(value):
    return re.sub(r"\s+", " ", _UNSAFE.sub("", unicodedata.normalize("NFC", value))).strip()


class _Text:
    def __init__(self, maximum):
        self.maximum, self.size, self.truncated = maximum, 0, False
        self.parts = []

    def add(self, value):
        value = re.sub(r"\s+", " ", _UNSAFE.sub("", unicodedata.normalize("NFC", value)))
        if self.parts and self.parts[-1].endswith(" ") and value.startswith(" "):
            value = value[1:]
        if not value:
            return
        raw = value.encode("utf-8")
        room = self.maximum - self.size
        if len(raw) > room:
            self.truncated = True
            raw = raw[:room]
        accepted = raw.decode("utf-8", "ignore")
        self.size += len(accepted.encode("utf-8"))
        if accepted:
            self.parts.append(accepted)

    def value(self):
        return _clean("".join(self.parts))


class _Article(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.tags, self.stack = base, 0, []
        self.text, self.title, self.link_label = _Text(MAX_TEXT), _Text(512), None
        self.link_url = None
        self.links, self.seen = [], set()

    def _hidden(self):
        return any(tag in _SKIP or hidden for tag, hidden in self.stack)

    def handle_starttag(self, tag, attrs):
        self.tags += 1
        if self.tags > MAX_TAGS or len(attrs) > 32:
            _fail()
        for name, value in attrs:
            if len(name.encode("utf-8")) > 8192 or value is not None and len(value.encode("utf-8")) > 8192:
                _fail()
        fields = dict(attrs)
        hidden = "hidden" in fields or (fields.get("aria-hidden") or "").lower() == "true"
        if tag not in _VOID:
            self.stack.append((tag, hidden))
            if len(self.stack) > MAX_DEPTH:
                _fail()
        if self._hidden() or hidden or tag in _SKIP:
            return
        if tag in _BLOCK:
            self.text.add(" ")
        if tag == "a":
            self._end_link()
            try:
                href = fields.get("href")
                self.link_url = normalize_preview_url(urljoin(self.base, href)).canonical_url if isinstance(href, str) else None
            except (LinkPreviewPolicyError, ValueError, UnicodeError):
                self.link_url = None
            if self.link_url is not None:
                self.link_label = _Text(256)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def _end_link(self):
        if self.link_url is not None and self.link_label is not None:
            if self.link_url not in self.seen and len(self.links) < MAX_LINKS:
                self.seen.add(self.link_url)
                self.links.append({"url": self.link_url, "text": self.link_label.value()})
        self.link_url = self.link_label = None

    def handle_endtag(self, tag):
        if tag in _BLOCK and not self._hidden():
            self.text.add(" ")
        if tag == "a":
            self._end_link()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self._hidden():
            return
        if any(tag == "title" for tag, _ in self.stack):
            self.title.add(data)
            return
        if any(tag == "head" for tag, _ in self.stack):
            return
        self.text.add(data)
        if self.link_label is not None:
            self.link_label.add(data)


def extract_page(body: bytes, content_type: str, final_url: str) -> dict:
    try:
        base = normalize_preview_url(final_url).canonical_url
        decoded = decode_research_text(body, content_type)
        if content_type.split(";", 1)[0].strip().lower() == "text/plain":
            text = _Text(MAX_TEXT)
            text.add(decoded)
            return {"status": "ready", "final_url": base, "title": "", "text": text.value(),
                    "text_truncated": text.truncated, "links": []}
        parser = _Article(base)
        parser.feed(decoded)
        parser.close()
        parser._end_link()
        return {"status": "ready", "final_url": base, "title": parser.title.value(),
                "text": parser.text.value(), "text_truncated": parser.text.truncated, "links": parser.links}
    except (LinkPreviewPolicyError, UnicodeError, ValueError, RecursionError):
        _fail()
