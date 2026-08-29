from __future__ import annotations

import unittest

from link_preview_metadata import (
    LinkPreviewMetadataError,
    decode_html,
    parse_metadata,
)


class LinkPreviewMetadataTests(unittest.TestCase):
    def test_open_graph_priority_and_safe_projection(self):
        html = """<!doctype html><html><head>
        <title>Document title</title>
        <meta name="twitter:title" content="Twitter title">
        <meta property="og:title" content="OG &amp; title">
        <meta name="description" content="ordinary description">
        <meta property="og:description" content="  OG\t description  ">
        <meta property="og:site_name" content="Example Site">
        <meta property="og:url" content="https://attacker.example/replacement">
        <meta property="og:image" content="https://images.example/fallback.png">
        <meta property="og:image:secure_url" content="https://images.example/secure.png">
        <meta property="og:image:alt" content="Preview alt">
        </head><body><meta property="og:title" content="Too late"></body></html>"""
        result = parse_metadata(html, display_host="www.example.com")
        self.assertEqual(result.title, "OG & title")
        self.assertEqual(result.description, "OG description")
        self.assertEqual(result.site_name, "Example Site")
        self.assertEqual(result.display_host, "www.example.com")
        self.assertEqual(result.image_candidate, "https://images.example/secure.png")
        self.assertEqual(result.image_alt, "Preview alt")
        self.assertNotIn("attacker", repr(result))

    def test_title_and_host_fallback_and_no_metadata(self):
        result = parse_metadata("<html><head><title>  Useful\n title </title></head></html>", display_host="example.com")
        self.assertEqual(result.title, "Useful title")
        self.assertIsNone(result.description)
        self.assertEqual(result.site_name, "example.com")
        empty = parse_metadata("<html><head></head></html>", display_host="minimal.example")
        self.assertIsNone(empty.title)
        self.assertIsNone(empty.description)

    def test_controls_bidi_duplicates_and_late_body_values_are_bounded(self):
        html = """<head>
        <meta property="og:title" content="safe\u202E title\u0001">
        <meta property="og:title" content="second">
        <meta property="og:description" content="first">
        <meta property="og:description" content="second">
        <body><meta property="og:site_name" content="late"></body>"""
        result = parse_metadata(html, display_host="example.com")
        self.assertEqual(result.title, "safe title")
        self.assertEqual(result.description, "first")
        self.assertEqual(result.site_name, "example.com")
        long = parse_metadata(f'<meta property="og:title" content="{"x" * 300}">', display_host="example.com")
        self.assertEqual(len(long.title or ""), 200)

    def test_structure_bounds_fail_closed(self):
        too_many_tags = "".join("<meta name='description' content='x'>" for _ in range(257))
        with self.assertRaises(LinkPreviewMetadataError):
            parse_metadata(too_many_tags, display_host="example.com")
        too_many_attributes = "<meta " + " ".join(f"data-{index}='x'" for index in range(33)) + ">"
        with self.assertRaises(LinkPreviewMetadataError):
            parse_metadata(too_many_attributes, display_host="example.com")
        with self.assertRaises(LinkPreviewMetadataError):
            parse_metadata("<meta name='description' content='" + "x" * 8193 + "'>", display_host="example.com")

    def test_charset_and_mime_policy_is_deterministic(self):
        self.assertEqual(decode_html(b"\xef\xbb\xbf<title>snowman \xe2\x98\x83</title>", "text/html; charset=windows-1252"), "<title>snowman ☃</title>")
        self.assertIn("café", decode_html("<title>café</title>".encode("cp1252"), "text/html; charset=iso-8859-1"))
        meta = b'<meta charset="windows-1252"><title>caf\xe9</title>'
        self.assertIn("café", decode_html(meta, "text/html"))
        self.assertIn("�", decode_html(b"<title>\xff</title>", "text/html"))
        with self.assertRaises(LinkPreviewMetadataError):
            decode_html(b"<title>x</title>", "text/plain")
        with self.assertRaises(LinkPreviewMetadataError):
            decode_html(b"<title>x</title>", "text/html; charset=shift_jis")
        with self.assertRaises(LinkPreviewMetadataError):
            decode_html(b"<title>x</title>", "application/xhtml+xml; charset=windows-1252")
        with self.assertRaises(LinkPreviewMetadataError):
            decode_html(b"<meta charset='shift_jis'><title>x</title>", "text/html")

    def test_unknown_html_is_inert_text_only(self):
        result = parse_metadata(
            '<script>alert(1)</script><style>x</style><iframe src="x"></iframe>'
            '<meta property="og:title" content="&lt;img src=x onerror=alert(1)&gt;">',
            display_host="example.com",
        )
        self.assertEqual(result.title, "<img src=x onerror=alert(1)>")
        self.assertNotIn("script", result.__dict__)


if __name__ == "__main__":
    unittest.main()
