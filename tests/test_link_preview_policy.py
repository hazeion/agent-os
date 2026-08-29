from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from link_preview_policy import (
    LinkPreviewPolicyError,
    MAXIMUM_DNS_ANSWERS,
    MAXIMUM_URL_BYTES,
    normalize_preview_url,
    validate_public_addresses,
)


class LinkPreviewURLPolicyTests(unittest.TestCase):
    def assert_policy_error(self, value: str, code: str | None = None) -> None:
        with self.assertRaises(LinkPreviewPolicyError) as raised:
            normalize_preview_url(value)
        if code is not None:
            self.assertEqual(raised.exception.code, code)
        self.assertNotIn(value, str(raised.exception))

    def test_u1_canonical_public_https_serialization(self):
        cases = (
            (
                "HTTPS://Example.dev:443/a/./b/../c/%7euser?q=%41#ignored",
                "https://example.dev/a/c/~user?q=A",
                "example.dev",
                "/a/c/~user?q=A",
            ),
            ("https://example.dev", "https://example.dev/", "example.dev", "/"),
            (
                "https://example.dev/a//b/../c?b=2&a=One%2ftwo",
                "https://example.dev/a//c?b=2&a=One%2Ftwo",
                "example.dev",
                "/a//c?b=2&a=One%2Ftwo",
            ),
        )
        for raw, canonical, host, target in cases:
            with self.subTest(raw=raw):
                normalized = normalize_preview_url(raw)
                self.assertEqual(normalized.canonical_url, canonical)
                self.assertEqual(normalized.host, host)
                self.assertEqual(normalized.request_target, target)
                self.assertFalse(normalized.is_ip_literal)

        prefix = "https://example.dev/"
        exact = prefix + "a" * (MAXIMUM_URL_BYTES - len(prefix))
        self.assertEqual(len(normalize_preview_url(exact).canonical_url), MAXIMUM_URL_BYTES)
        self.assert_policy_error(exact + "a")
        self.assertEqual(
            normalize_preview_url(prefix + "#" + "x" * 3_000).canonical_url,
            prefix,
        )

    def test_u2_rejects_unsupported_or_ambiguous_url_syntax_before_network(self):
        cases = (
            "http://example.dev/",
            "file:///etc/passwd",
            "data:text/plain,hello",
            "gopher://example.dev/",
            "javascript:alert(1)",
            "//example.dev/path",
            "https://user@example.dev/",
            "https://" + "user:password@" + "example.dev/",
            "https://example.dev:444/",
            "https://example.dev\\@127.0.0.1/",
            "https://example.dev/%5cprivate",
            "https://example.dev/%ZZ",
            "https://example.dev/ has-space",
            " https://example.dev/",
            "https://example.dev/\x00tail",
            "https://example.dev/\u202etail",
        )
        for value in cases:
            with self.subTest(value=repr(value)):
                self.assert_policy_error(value)

    def test_u3_ip_literals_must_be_canonical_and_public(self):
        public = normalize_preview_url("https://8.8.8.8/path")
        self.assertEqual(public.host, "8.8.8.8")
        self.assertTrue(public.is_ip_literal)
        public_v6 = normalize_preview_url("https://[2606:4700:4700::1111]/")
        self.assertEqual(public_v6.host, "2606:4700:4700::1111")
        self.assertTrue(public_v6.is_ip_literal)
        mapped = normalize_preview_url("https://[::ffff:8.8.8.8]/")
        self.assertTrue(mapped.is_ip_literal)

        for value in (
            "https://2130706433/",
            "https://127.1/",
            "https://0177.0.0.1/",
            "https://0x7f.0.0.1/",
            "https://１２７。０。０。１/",
            "https://８。８。８。８/",
            "https://127.0.0.1/",
            "https://[::1]/",
            "https://[2001:DB8::1]/",
            "https://[fe80::1%25en0]/",
            "https://[2002:0808:0808::1]/",
        ):
            with self.subTest(value=value):
                self.assert_policy_error(value)

    def test_u4_idna_host_and_component_normalization(self):
        unicode_host = normalize_preview_url("https://faß.de./café")
        alabel_host = normalize_preview_url("https://xn--fa-hia.de/caf%C3%A9")
        self.assertEqual(unicode_host.canonical_url, alabel_host.canonical_url)
        self.assertEqual(unicode_host.host, "xn--fa-hia.de")
        self.assertEqual(
            normalize_preview_url("https://python\u3002org/").host,
            "python.org",
        )

        normalized = normalize_preview_url(
            "https://example.dev/a/%2E%2e/b/%2F?q=%7e%2f"
        )
        self.assertEqual(normalized.canonical_url, "https://example.dev/b/%2F?q=~%2F")

        invalid_hosts = (
            "https://bad..example.dev/",
            "https://example.dev../",
            "https://-bad.example.dev/",
            "https://bad_.example.dev/",
            "https://\u200d.example.dev/",
            "https://" + "a" * 64 + ".example.dev/",
            "https://" + ".".join(["a" * 63] * 5) + "/",
        )
        for value in invalid_hosts:
            with self.subTest(value=value):
                self.assert_policy_error(value)

        for host in (
            "localhost",
            "service.localhost",
            "printer.local",
            "router.home.arpa",
            "name.test",
            "name.invalid",
            "name.example",
            "example.com",
        ):
            with self.subTest(host=host):
                self.assert_policy_error(
                    f"https://{host}/",
                    "link_preview.blocked",
                )

        for query in (
            "access_token=value",
            "API_KEY=value",
            "password=value",
            "x-amz-signature=value",
            "x-goog-signature=value",
            "api%5Fkey=value",
            "ordinary=1;secret=value",
        ):
            with self.subTest(query=query):
                self.assert_policy_error(
                    f"https://example.dev/?{query}",
                    "link_preview.blocked",
                )

    def test_policy_never_calls_dns(self):
        with patch.object(
            socket,
            "getaddrinfo",
            side_effect=AssertionError("policy_must_not_resolve"),
        ):
            normalize_preview_url("https://python.org/")
            validate_public_addresses(("8.8.8.8", "2606:4700:4700::1111"))


class LinkPreviewAddressPolicyTests(unittest.TestCase):
    def assert_address_error(self, values, code: str | None = None) -> None:
        with self.assertRaises(LinkPreviewPolicyError) as raised:
            validate_public_addresses(values)
        if code is not None:
            self.assertEqual(raised.exception.code, code)
        for value in values if isinstance(values, (tuple, list)) else ():
            self.assertNotIn(str(value), str(raised.exception))

    def test_d1_rejects_every_representative_non_global_class(self):
        addresses = (
            "0.0.0.0",
            "10.0.0.1",
            "100.64.0.1",
            "127.0.0.1",
            "169.254.1.1",
            "172.16.0.1",
            "192.0.0.1",
            "192.0.2.1",
            "192.168.1.1",
            "198.18.0.1",
            "198.51.100.1",
            "203.0.113.1",
            "224.0.0.1",
            "240.0.0.1",
            "::",
            "::1",
            "64:ff9b::808:808",
            "100::1",
            "100:0:0:1::1",
            "2001:db8::1",
            "2002:808:808::1",
            "3fff::1",
            "fc00::1",
            "fe80::1",
            "ff02::1",
        )
        for address in addresses:
            with self.subTest(address=address):
                self.assert_address_error((address,), "link_preview.blocked")

    def test_globally_reachable_special_registry_exceptions_remain_eligible(self):
        result = validate_public_addresses(
            (
                "192.0.0.9",
                "192.0.0.10",
                "2001:1::1",
                "2001:3::1",
                "2001:4:112::1",
                "2001:20::1",
                "2001:30::1",
            )
        )
        self.assertEqual(len(result.addresses), 7)

    def test_d2_mixed_safe_and_unsafe_set_is_wholly_blocked(self):
        self.assert_address_error(
            ("8.8.8.8", "127.0.0.1"),
            "link_preview.blocked",
        )

    def test_d3_returns_only_canonical_supplied_numeric_targets(self):
        result = validate_public_addresses(
            ("2606:4700:4700::1111", "8.8.8.8", "8.8.8.8")
        )
        self.assertEqual(
            result.addresses,
            ("2606:4700:4700::1111", "8.8.8.8"),
        )
        self.assertEqual(
            result.connection_candidates,
            ("2606:4700:4700::1111", "8.8.8.8"),
        )

    def test_d4_special_names_are_rejected_without_resolver_use(self):
        with patch.object(
            socket,
            "getaddrinfo",
            side_effect=AssertionError("special_name_must_not_resolve"),
        ):
            for host in ("localhost", "service.local", "name.test"):
                with self.subTest(host=host):
                    with self.assertRaises(LinkPreviewPolicyError):
                        normalize_preview_url(f"https://{host}/")

    def test_d5_answer_and_connection_attempt_bounds(self):
        too_many = tuple(f"8.8.8.{index}" for index in range(1, MAXIMUM_DNS_ANSWERS + 2))
        self.assert_address_error(too_many, "link_preview.answer_limit")

        result = validate_public_addresses(
            (
                "2606:4700:4700::1111",
                "2606:4700:4700::1001",
                "8.8.8.8",
                "8.8.4.4",
            )
        )
        self.assertEqual(len(result.connection_candidates), 2)
        self.assertEqual(
            result.connection_candidates,
            ("2606:4700:4700::1111", "8.8.8.8"),
        )

    def test_empty_invalid_scoped_and_noncanonical_answers_fail_closed(self):
        for values in (
            (),
            ("not-an-address",),
            ("fe80::1%en0",),
            ("2606:4700:4700:0:0:0:0:1111",),
        ):
            with self.subTest(values=values):
                self.assert_address_error(values)


if __name__ == "__main__":
    unittest.main()
