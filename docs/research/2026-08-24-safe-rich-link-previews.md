# Safe rich-link previews: research and security decision

**Date:** 2026-08-24

**Ticket:** [#130](https://github.com/hazeion/agent-os/issues/130)

**Decision type:** read/research-only; no production implementation is authorized by this document.

## Decision summary

Mentat should support best-effort previews for public HTTPS links, but the
preview must be a narrow Python-owned capability, not a browser fetch and not a
generic Node-to-Python proxy. The browser submits a durable Conversation
message first. A fixed Node route may then request preview work for that
message; Python extracts the candidate URLs, performs all parsing, DNS/IP
checks, network I/O, metadata parsing, image processing, caching, and output
projection. The browser receives only bounded sanitized fields and opaque
same-origin media IDs.

The plain link is the product invariant: it is rendered immediately and stays
usable if the preview is pending, blocked, malformed, offline, timed out, or
unsupported. Preview failure must never fail message submission or turn an
external link into an error state that prevents navigation.

The recommended initial defaults are:

| Control | Initial default | Rationale |
| --- | ---: | --- |
| URLs per submitted message | 3 | Bounds work and tracking exposure. Extra URLs remain plain links. |
| URL length | 2,048 ASCII bytes after canonical serialization | Bounds the exact value used for DNS, HTTP, redirects, and cache identity. |
| Allowed scheme | `https` only | No HTTP downgrade, `file:`, `data:`, `gopher:`, `javascript:`, or other schemes. |
| Allowed port | 443 only, including an explicit `:443` | Avoids turning previews into a public-port scanner. |
| Redirects | At most 3 followed redirects (4 HTTP requests total) | Each `Location` is parsed, normalized, resolved, and revalidated before the next connection. |
| Total operation deadline | 5 seconds per page or image operation, including redirects, transfer, parsing/decoding, and re-encoding; 5.25-second parent watchdog | One monotonic deadline plus a hard process-level stop for an uninterruptible resolver or decoder. |
| DNS deadline | 1 second | DNS is part of the total deadline. |
| DNS/address work | At most 16 A/AAAA answers and 2 pinned connection attempts per hop | Every answer must be public; address-family fallback cannot become unbounded scanning. |
| Connect + TLS deadline | 2 seconds | Includes TCP connect and certificate-verified TLS handshake. |
| Header/idle-read deadline | 1 second without progress | A slow server cannot hold a worker indefinitely. |
| HTML response body | 512 KiB encoded; 1 MiB decoded | Enforces both compressed and decompressed limits. |
| Response headers | 32 KiB total, 64 fields, 8 KiB per field | Prevents header-count and individual-field abuse before parsing the body. |
| Content codings | Page: `identity` or one `gzip`; image: `identity` only | Unknown, `deflate`, Brotli, Zstandard, and stacked codings fail closed initially. |
| HTML MIME types | `text/html`, `application/xhtml+xml` | MIME parameters are parsed; unsupported or missing types use fallback. |
| Image fetch body | 2 MiB encoded | Enforced while streaming, regardless of `Content-Length`. |
| Image decode | 4 megapixels and 2,048 px per dimension | Separate from compressed-byte limits; reject decompression bombs and extreme dimensions. |
| Image output | One static WebP, fit within 1,200 x 1,200 px, 512 KiB maximum | No original image container or external image URL is embedded in the Console. |
| Ready metadata/image cache | 24 hours by default; origin freshness may shorten it; never more than 24 hours | Limits repeat disclosure to origins while keeping derived data short-lived. |
| Negative cache | 5 minutes for `unavailable`; 1 hour for `blocked` | Prevents repeated hostile work without making transient network failure sticky. |
| Cache capacity | 512 metadata entries and 64 MiB of transformed images, LRU | Cache growth is bounded independently of message history. |
| Rich-link setting | Enabled by default, global opt-out | Matches the Console specification while giving a clear privacy control. |
| Fetch concurrency | 2 preview jobs per Mentat process | A local server should not become a fan-out worker. |

These numbers are product defaults, not evidence that a larger value is safe.
Any relaxation requires a new decision and hostile-server evidence.

## Authority and boundary

The repository authority is explicit. The pivot keeps Mentat local and
loopback-only, places the browser behind the Node gateway, and leaves Python as
the authority for data, files, credentials, Hermes, and safety checks
([`MENTAT_MULTI_AGENT_PIVOT.md`](../../MENTAT_MULTI_AGENT_PIVOT.md),
[`ARCHITECTURE.md`](../../ARCHITECTURE.md)).
The Next.js Console specification already describes rich links as a separate
server capability that accepts normalized public HTTPS URLs, sends no browser
credentials, revalidates redirects and DNS, parses bounded metadata, proxies
permitted images, and exposes a plain-link fallback
([`MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md`](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md)).
The implementation plan says each frontend slice adds only the bridge and Node
capabilities it needs; it does not add a generic Python proxy
([`MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`](../../MENTAT_PIVOT_IMPLEMENTATION_PLAN.md)).

The proposed flow is therefore:

```text
submitted Conversation message
        |
        v
fixed Node request: message identity + current revision only
        |
        v
fixed private Python capability
        |
        +-- extract and normalize HTTPS candidates
        +-- resolve, classify, pin, fetch, parse, and bound
        +-- optional separate image fetch and re-encode
        v
private cache / opaque media store
        |
        v
same-origin sanitized preview projection + always-available plain link
```

The browser must not provide a bridge path, destination headers, proxy, IP,
credential, cookie, runtime reference, or arbitrary fetch target. A preview
request should refer to the already-committed message ID and revision; Python
reads the canonical safe content and extracts up to the configured limit. That
keeps the network capability from becoming a URL oracle and binds work to
Mentat-owned Conversation state.

## Threat model

The external URL, its DNS responses, every redirect, HTTP response, HTML
metadata value, and image bytes are hostile. The local user may also paste
URLs designed to make Mentat probe local services. The protected assets are the
Mentat process, loopback services, private networks, cloud metadata endpoints,
operator credentials, browser cookies, private Console data, and the
availability and privacy of the local app.

| Threat | Failure mode | Required control |
| --- | --- | --- |
| SSRF to loopback/private/metadata | Fetch reaches Mentat, a LAN service, or a cloud metadata IP. | Resolve every A/AAAA answer; reject any non-global destination before connect; use the chosen IP directly; repeat for redirects and images. |
| DNS rebinding | Validation resolves a public address, but the actual connect resolves a private address. | Pin the validated numeric address for that connection; do not hand the hostname to a second resolver; verify the connected peer address. |
| Redirect bypass | A public page redirects to private IP, HTTP, a special scheme, or an unbounded chain. | Disable automatic redirects; allow only HTTPS `Location` targets; reparse and revalidate every hop; stop at three. |
| URL parser confusion | Credentials, backslashes, Unicode, alternate IP spellings, or a nested scheme bypass a string filter. | Use a standards-based parser plus explicit allowlists; reject userinfo, controls, backslashes, ambiguous hosts, non-443 ports, and unsupported schemes. |
| Credential and cookie leakage | Mentat sends browser cookies, provider credentials, proxy credentials, client certificates, `Referer`, or URL bearer tokens. | Construct a fixed header set; use no cookie jar, auth, client certificate, proxy, or referrer; never log raw URLs; reject obvious credential-bearing userinfo/query patterns. |
| Compression/decode exhaustion | A small gzip body expands beyond memory or CPU limits. | Count encoded bytes while reading and decoded bytes while decompressing; fail at either cap; accept only one gzip coding for pages and identity for images; never buffer an unbounded body. |
| HTML parser/XSS | Remote HTML becomes executable browser markup or makes parsing consume unbounded resources. | Parse only bounded bytes for selected meta attributes; discard tags and scripts; return strings only; render with text-safe framework sinks; never return HTML. |
| Image decompression bomb/polyglot | A tiny image consumes memory/CPU, carries hidden metadata, or is interpreted as active content. | Allowlist JPEG/PNG/WebP; enforce encoded bytes, dimensions, pixels, and output bytes; verify and re-encode through bounded Pillow; strip metadata; do not support SVG, PDF, TIFF, animation, or arbitrary formats. |
| Cache poisoning or cross-target confusion | A response for one URL is shown for another or a redirect/image changes the meaning of a cache entry. | Versioned, type-separated keyed digests over normalized URLs; bind policy/parser/transform versions; never key on raw unnormalized input; isolate disposable cache entries to one owner-private data root. |
| Tracking and privacy leakage | Preview requests reveal message contents, local IP, or browsing interest. | Fetch only submitted links; no cookies/referrer; global opt-out; bounded concurrency; no automatic retries; cache-only behavior offline; no raw URLs in audit/logs. |
| Availability abuse | A hostile server holds workers, returns large bodies, or creates many image requests. | Per-fetch deadlines, per-message URL cap, process concurrency cap, no JavaScript, one image, negative caching, and plain-link fallback. |

OWASP's SSRF guidance specifically calls out unsafe redirects, DNS rebinding,
alternate IP representations, and the need to disable automatic redirect
handling and validate redirects; its Node guidance also warns that a safe first
resolution is not sufficient ([SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html),
[SSRF Prevention in Node.js](https://owasp.org/www-community/pages/controls/SSRF_Prevention_in_Nodejs.html)).

## Bounded fetch contract

### 1. Candidate extraction and normalization

Extraction happens only after the message is durably accepted. It should use
plain-text URL candidates from the safe message content, not HTML parsing or
model-provided fetch instructions. Each candidate is normalized once and
compared by its canonical serialization.

The [WHATWG URL Standard](https://url.spec.whatwg.org/) is the reference model
for parsing and serializing browser-facing URLs. Python's own documentation
warns that `urllib.parse.urlsplit()` does not validate input, may accept values
other applications do not consider URLs, and requires defensive verification
for security-sensitive use ([`urllib.parse` security](https://docs.python.org/3/library/urllib.parse.html#url-parsing-security)).
Accordingly, `urlsplit()` or a regex may be a component of an implementation,
but neither is the security boundary.

The validator should:

1. Reject control characters, NUL, raw or encoded backslashes, whitespace in
   the authority, malformed percent escapes, scheme-relative input, userinfo,
   empty hosts, more than one trailing DNS dot, ambiguous IPv4 spellings, and
   canonical serializations longer than 2,048 ASCII bytes. Decimal-dword,
   octal-like, hexadecimal, shortened IPv4, and scoped IPv6 literals are
   rejected rather than interpreted.
2. Parse as an absolute URL and require `https`, host present, and port 443 or
   absent. Remove one terminal DNS root dot, lowercase the scheme and DNS host,
   convert each IDN label with UTS #46 nontransitional processing and STD3
   rules, validate DNS label/host lengths, and use the resulting ASCII A-label
   for resolution, SNI, `Host`, and cache identity. An IP literal must already
   be canonical dotted-decimal IPv4 or RFC-compressed IPv6.
3. Serialize an empty path as `/`, remove RFC 3986 dot segments, uppercase the
   hex digits in percent triplets, and decode percent-encoding only for
   unreserved characters. Never decode a reserved delimiter before splitting
   components, and do not reorder or case-fold the query.
4. Drop the fragment for fetching and cache identity. Fragments are not sent
   in an HTTP request and should not create multiple fetches for the same
   resource. The original message remains the display/link source.
5. Reject userinfo unconditionally. Query strings remain allowed for
   compatibility, but high-confidence credential/signature parameter names
   (`access_token`, `api_key`, `password`, `secret`, `signature`, `sig`,
   `x-amz-signature`, and `x-goog-signature`, case-insensitive) make the link
   ineligible for automatic preview. The original plain link still works.
6. Apply the same validator to every redirect target and every `og:image` or
   fallback image URL. Relative metadata URLs are resolved against the final
   page URL, then undergo the full validation again. The page's `og:url` is
   ignored; it must not replace the user's link target or enter the preview
   projection/cache.

The URL standard defines credentials as a distinct URL component and defines
host/IP parsing and serialization; these are reasons to parse first and
compare the normalized result, rather than searching for suspicious substrings
in the original string ([WHATWG URL host parsing](https://url.spec.whatwg.org/#host-parsing),
[WHATWG URL credentials](https://url.spec.whatwg.org/#include-credentials)).
UTS #46 defines nontransitional IDNA processing and STD3 rules
([Unicode UTS #46](https://unicode.org/reports/tr46/)); RFC 3986 defines
fragment, percent-encoding, and dot-segment normalization without treating
reserved and unreserved characters as interchangeable
([RFC 3986](https://www.rfc-editor.org/rfc/rfc3986.html)).

### 2. DNS/IP validation and connection pinning

For a DNS hostname, resolve A and AAAA records through the configured system
resolver within the DNS deadline. Accept at most 16 distinct answers and
validate every one. A hostname with no answer, too many answers, an error, or
any unsafe answer is blocked; do not choose a different “safe” answer from a
mixed set. For an IP literal, classify the literal directly and do not
re-resolve it.

The allow decision should be “globally reachable” according to the current
[IANA IPv4 Special-Purpose Address Registry](https://www.iana.org/assignments/iana-ipv4-special-registry)
and [IANA IPv6 Special-Purpose Address Registry](https://www.iana.org/assignments/iana-ipv6-special-registry),
not merely “does not look private.” This rejects loopback, unspecified,
link-local, private-use, shared address space, multicast, documentation,
benchmarking, protocol-reserved, unique-local, IPv4-mapped private addresses,
and other non-global destinations. The registries explicitly record whether a
prefix is globally reachable. The implementation should carry a reviewed,
source-controlled deny table for every current IANA special-purpose prefix and
also require Python's `ipaddress.is_global`; this avoids a supported Python
minor version's embedded table being the only policy source
([`ipaddress`](https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_global)).
IPv4-mapped IPv6 is reduced to IPv4 before both checks; scoped, transition, and
translation forms are rejected initially.
Reject special-use names such as `localhost`, `.localhost`, `.local`,
`.home.arpa`, `.test`, `.invalid`, and `.example` before DNS as an additional
defense, using the
[IANA Special-Use Domain Names registry](https://www.iana.org/assignments/special-use-domain-names/);
the IP check remains authoritative.

The connection must be pinned as follows:

- choose from the already-validated answer set and attempt at most two
  addresses per hop (at most one IPv6 and one IPv4); this family fallback is
  not permission to re-resolve or retry the request;
- create the TCP socket to that numeric address, never to the hostname;
- for HTTPS, wrap that connected socket with a default certificate-validating
  `SSLContext` and pass the original canonical hostname as `server_hostname`
  for SNI and certificate hostname verification;
- send the original canonical hostname in `Host`, with a fixed `Connection:
  close`, and verify the peer address is the selected address;
- do not use an environment proxy, pooled connection, automatic redirect, or
  automatic retry; close the connection after the bounded response.

This is a direct-dial design based on Python's documented socket and TLS
primitives: `SSLContext.wrap_socket()` accepts a connected socket and
`server_hostname`, while `create_default_context()` enables secure client
defaults ([Python `ssl`](https://docs.python.org/3/library/ssl.html#ssl.create_default_context),
[Python `SSLContext.wrap_socket`](https://docs.python.org/3/library/ssl.html#ssl.SSLContext.wrap_socket)).
The pinning conclusion is an implementation inference from those primitives;
it must be proven by a test that records the numeric dial target and SNI name.
Python's socket documentation also recommends a numeric host for deterministic
connection behavior and exposes `getpeername()` for checking the connected
remote address ([Python `socket`](https://docs.python.org/3/library/socket.html)).

The long-lived Python bridge must not perform hostile DNS, socket, parsing, or
image-decode work inline. Use a fixed pool of two replaceable Python workers
with a minimal allowlisted environment. In practice this means no `HOME` or
`NETRC`, proxy, Requests/curl CA override, provider, bridge-token, cookie, or
client-certificate inputs, plus a transport that never consults a cookie jar or
authentication file. A worker receives only the normalized URL and fixed
policy over private IPC, receives no SQLite/Console file descriptors or paths,
and exposes no Hermes, Console-file, or generic file capability. The parent
observes phase progress, closes/kills a worker when DNS exceeds one second or
the complete operation exceeds 5.25 seconds, and replaces it before accepting
more work.
This outer watchdog is required because `getaddrinfo()` delegates to the
platform resolver and ordinary socket timeouts do not by themselves prove a
hard DNS or whole-operation deadline; that is an inference from Python's
documented OS-backed resolver and socket timeout behavior
([Python `socket.getaddrinfo`](https://docs.python.org/3/library/socket.html#socket.getaddrinfo)).

### 3. Request and redirect behavior

Use one fixed, credential-free GET profile for each resource class. Do not send
a preliminary `HEAD`; it doubles disclosure and servers often implement it
differently from `GET`.

```text
# page
User-Agent: MentatLinkPreview/1
Accept: text/html, application/xhtml+xml;q=0.9
Accept-Encoding: gzip
Connection: close

# image
User-Agent: MentatLinkPreview/1
Accept: image/webp, image/png;q=0.9, image/jpeg;q=0.9
Accept-Encoding: identity
Connection: close
```

Do not send `Cookie`, `Authorization`, `Proxy-Authorization`, `Referer`,
`Origin`, a browser user-agent, a client certificate, or Mentat/provider
credentials. Do not process `Set-Cookie`. The Fetch Standard treats cookies,
TLS client certificates, and HTTP authentication entries as credentials
([Fetch credentials](https://fetch.spec.whatwg.org/#credentials)); RFC 6265
describes cookies as state that a user agent returns on later requests and
warns about their ambient-authority implications ([RFC 6265](https://www.rfc-editor.org/rfc/rfc6265.html)).
Omit `Accept-Language` and detailed platform/version tokens: RFC 9110 notes
that detailed `User-Agent` values increase fingerprinting risk and that
`Accept-Language` can reveal user information
([RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#field.user-agent)).

Read the response status and headers before accepting a body. For 301, 302,
303, 307, and 308 with a usable `Location`, resolve the location against the
current URL, normalize it, enforce HTTPS/443, perform DNS/IP validation again,
and open a new pinned connection. Count hops, detect cycles by normalized URL,
and stop after three. A redirect to HTTP is blocked rather than upgraded or
followed. RFC 9110 defines redirects as a new target and says automatically
following one requires replacing the target and removing sensitive fields such
as `Authorization` and `Cookie`; the fixed contract sends none in the first
place ([RFC 9110 redirection](https://www.rfc-editor.org/rfc/rfc9110.html#name-redirection-3xx)).

Only a final 200 response is eligible for metadata or image parsing. Other
statuses produce an unavailable result while retaining the plain link. No
automatic retry follows timeouts, DNS failures, TLS failures, malformed
redirects, or ambiguous responses.

### 4. Time, headers, compression, and MIME

Use a monotonic five-second total deadline for each page/image operation. DNS,
all redirect hops, connect/TLS, header and body reads, decompression, parsing,
image decode, and image re-encoding consume the same remaining budget. A
one-second idle-read limit is not a substitute for the total deadline.

Count response-header bytes, fields, and each field before body processing.
Then count encoded body
bytes as received and decoded bytes as decompression produces them. Reject
before allocating beyond the configured limit; do not trust `Content-Length`,
because chunked and compressed responses can make it incomplete or misleading.
Accept only one gzip coding or identity for pages and identity for images;
reject deflate, Brotli, Zstandard, unknown, or stacked codings in the first
version. HTTP defines
`Content-Encoding` as a transformation applied around the media type and
defines `Content-Type` as the type after decoding ([RFC 9110 representation
metadata](https://www.rfc-editor.org/rfc/rfc9110.html#name-representation-data-and-metadata),
[RFC 9110 content encoding](https://www.rfc-editor.org/rfc/rfc9110.html#name-content-encoding)).

Do not MIME-sniff arbitrary bytes into an allowed type. The MIME Sniffing
standard explains that incorrect server MIME types can create security issues,
especially when content believed to be an image is interpreted as HTML
([WHATWG MIME Sniffing](https://mimesniff.spec.whatwg.org/)). Require the
allowlisted MIME type after parameters are removed:

- page: `text/html` or `application/xhtml+xml`;
- image: `image/jpeg`, `image/png`, or `image/webp`.

No SVG, HTML, XML-as-image, PDF, TIFF, AVIF, APNG, GIF, video, audio, or
generic `application/octet-stream` is accepted in the initial image proxy.
This is deliberately narrower than browser compatibility; unsupported content
gets a plain link.

### 5. HTML parsing and safe projection

The only page parser is a bounded metadata collector. It should stop after the
first `<body>`, a closing `</head>`, 256 start tags, or the 1 MiB decoded limit,
whichever comes first. Cap each tag at 32 attributes and each attribute value at
8 KiB. Ignore scripts, styles, forms, iframes, embedded media, refresh
directives, `<base>`, and all page behavior. Resolve relative canonical/image
metadata only against the final fetched page URL, never against an untrusted
`<base>` element.

Decode with a fixed charset policy: honor a UTF-8 BOM first. Otherwise, if an
HTTP `charset` is present, accept only UTF-8, Windows-1252, or ISO-8859-1
(mapped to Windows-1252); an unknown or malformed HTTP label makes the preview
unavailable. If the HTTP header has no charset, inspect only the first 1,024
encoded bytes for an HTML `<meta charset>` declaration under the same
allowlist; an unknown or malformed declared label is unavailable. With no
declaration, use UTF-8 with replacement. For `application/xhtml+xml`, accept
only UTF-8.
The HTML Standard defines prescanning for encoding declarations within the
first 1,024 bytes, and the Encoding Standard defines the labels and the
ISO-8859-1-to-Windows-1252 mapping
([HTML encoding declarations](https://html.spec.whatwg.org/multipage/parsing.html#encoding-sniffing-algorithm),
[WHATWG Encoding](https://encoding.spec.whatwg.org/)).

Python's `HTMLParser` is a lenient parser for invalid HTML/XHTML and invokes
callbacks for tags and text ([Python `html.parser`](https://docs.python.org/3/library/html.parser.html));
that is sufficient for reading selected `meta` attributes without constructing
or rendering a document. If a future compatibility requirement needs full
HTML5 tree correction, it needs a separately reviewed parser dependency and
does not justify returning remote HTML.

Collect the first valid value for these fields, in priority order:

| Collector value | Accepted source | Bound |
| --- | --- | ---: |
| `title` | `og:title`, then `<title>`, then `twitter:title` | 200 Unicode code points |
| `description` | `og:description`, then `description`, then `twitter:description` | 500 |
| `site_name` | `og:site_name`, then validated host display name | 120 |
| transient `image_url` | `og:image:secure_url`, then `og:image`, then `twitter:image` | one worker-local candidate, normalized public HTTPS only |
| `image_alt` | `og:image:alt` | 200 |

Open Graph's own protocol defines the core properties and image structured
properties, including image type, dimensions, and alt text
([Open Graph protocol](https://ogp.me/)). Use declared type/dimensions only as
hints; the fetched bytes and Pillow verification are authoritative. Discard
the transient image URL after lookup/fetch, and ignore `og:url` and
`link[rel=canonical]`; neither belongs in persisted metadata or a browser
payload. The final fetched page's canonical ASCII host supplies
`display_host`.

Normalize extracted text to Unicode NFC, decode character references, replace
runs of whitespace with one space, remove C0/C1 controls and Unicode
`Bidi_Control` characters, and then truncate by Unicode code point before
persistence. Directional formatting controls affect display order and have
documented security implications
([Unicode Bidirectional Algorithm](https://www.unicode.org/reports/tr9/)).
Return JSON strings, not HTML. The
frontend must render them through React/text-safe properties and never use
`innerHTML` or a remote HTML fragment. OWASP recommends context-sensitive
output encoding and safe text sinks for untrusted values
([XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)).

The preview projection should contain only a status (`pending`, `ready`,
`unavailable`, or `blocked`), bounded text, the canonical ASCII display host
without path or query, and an opaque `image_id` when available. It should not
contain response headers, raw HTML,
redirect history, resolved IPs, DNS names, cookies, server banners, or the
external image URL. The original user link remains the navigation target.

### 6. Image proxying

Image fetching is a second bounded operation, not an incidental consequence of
parsing HTML. Apply the same URL, DNS, redirect, TLS, header, timeout, and
credential rules. Fetch at most one image for a card, prefer an HTTPS
`og:image:secure_url`, and do not use an HTTP image even if the page itself was
HTTPS. Do not allow an image to trigger further metadata discovery or redirects
beyond its own three-hop budget.

Stage the encoded bytes in an owner-only temporary file or bounded memory
buffer inside the replaceable worker. Require the declared MIME essence, magic
signature, and Pillow-detected format to agree. Turn
`DecompressionBombWarning` into an error, enforce the 4 MP and 2,048-pixel
limits before full decode, require exactly one frame, reject truncated or
animated content, apply orientation, copy pixels into a fresh RGB/RGBA image,
fit it within 1,200 x 1,200, and strip EXIF/XMP/ICC/text metadata. Encode one
static WebP (quality 80 for opaque content, lossless for alpha); if the
packaged Pillow build lacks WebP support or the result exceeds 512 KiB, omit
the image and retain the text card.

The transformed image belongs to a separate disposable owner-private preview
cache below the data root's runtime/cache class. It is not an Agent Console
attachment/artifact blob, transcript authority, backup member, compatible-root
member, or tracked file. Python maps a random opaque `image_id` to that cache
entry; neither Node nor the browser receives its path, keyed URL digest,
content hash, or external source URL. Use at least 128 bits from the operating
system CSPRNG for the ID. The fixed same-origin image route accepts only that
opaque ID and returns `Content-Type: image/webp`, exact `Content-Length`, a
`Cache-Control: private, max-age=N, no-transform` value where `N` is the smaller
of 300 and the entry's remaining whole-second lifetime, and
`X-Content-Type-Options: nosniff`. It cannot accept a URL and cannot fetch on a
cache miss.

Pillow is already a pinned dependency and its maintained security guidance
warns about decompression bombs, animated formats, parser complexity, hidden
metadata, and C-extension vulnerabilities. It recommends format allowlists,
pixel limits, metadata stripping, current dependencies, and hash-pinned
installation ([Pillow security](https://pillow.readthedocs.io/en/stable/handbook/security.html)).
If the runtime cannot provide the replaceable bounded worker for hostile image
bytes, the first release should return a metadata-only card and retain the
plain link; it should not decode inline or silently widen the accepted formats.

## Cache, privacy, and offline behavior

Cache only the sanitized result, never raw HTML or original image bytes. Keep
metadata and image caches in separate owner-private, disposable namespaces.
Use a 256-bit owner-only random cache-key secret from the operating system
CSPRNG that is excluded from backup; if it is missing or changes, discard the
cache. Python's `secrets` module documents that it uses the most secure source
of randomness provided by the operating system
([Python `secrets`](https://docs.python.org/3/library/secrets.html)). The
initial identities should be:

```text
link-metadata:<HMAC-SHA-256(cache-secret,
  policy-v1 || parser-v1 || fixed-request-profile || normalized-initial-url)>
link-image:<HMAC-SHA-256(cache-secret,
  policy-v1 || image-transform-v1 || normalized-image-url)>
```

Keying prevents a cache-directory observer from testing guessed URLs without
the owner-private secret; HMAC is the standard keyed-hash construction
([RFC 2104](https://www.rfc-editor.org/rfc/rfc2104.html)). The cache record
binds schema/policy/parser or transform version, initial and final keyed
digests, sanitized fields, random media ID, created time, expiry, and bounded
status. It does not need the raw initial, redirect, or image URL: Python derives
the key again from the canonical submitted message when needed. Outside the
canonical user-authored message, raw URLs never belong in logs, audits, browser
preview payloads, metrics labels, filenames, or exception text.

Use origin cache directives conservatively: honor `no-store` by not persisting
the result; because the first version has no conditional revalidation, also do
not persist `no-cache` or `Vary: *` responses. Recognize only a nonnegative
decimal `max-age` initially and ignore `Expires`; use the smaller of `max-age`
and 24 hours, or 24 hours when `max-age` is absent. A malformed, negative,
duplicate, or conflicting `max-age` makes the response non-persistable rather
than invoking a guess. A transformed image expires with its metadata entry and
never later than 24 hours. Cache
`unavailable` for five minutes and `blocked` for one hour. Enforce 512 metadata
entries and 64 MiB of transformed images with least-recently-used eviction;
never serve stale entries. RFC 9111 defines
a cache key as at
least the request method and target URI and describes freshness as the
relationship between freshness lifetime and current age ([RFC 9111 cache key](https://www.rfc-editor.org/rfc/rfc9111.html#name-cache-key),
[RFC 9111 freshness](https://www.rfc-editor.org/rfc/rfc9111.html#name-freshness-lifetime)).
Because Mentat uses one fixed GET/header profile and no credentials, the
keyed normalized URL plus explicit policy/parser/request-profile versions is
sufficient for the initial cache; if request negotiation is expanded, `Vary`
dimensions must be added or caching must be disabled for that response.

The global Rich link previews setting is read by Python before enqueueing new
work. Turning it off cancels queued work, closes in-flight sockets where
possible, suppresses cached cards in the UI, and leaves only plain links. Cache
deletion is a separate explicit **Clear link preview cache** control; otherwise
entries expire normally. Re-enabling does not retroactively refetch old
messages without an explicit retry.

The setting UI must explain that even a credential-free preview reveals the
machine's public source IP, the requested URL path/query, timing, and the fixed
Mentat user-agent to the destination and its network providers. Mentat must not
fetch drafts, pasted-but-unsent text, historical messages discovered at
startup, or links outside an explicit newly submitted message/retry. This makes
the enabled-by-default choice visible and reversible rather than claiming that
server-side fetching is anonymous.

There is no connectivity probe. When Mentat is explicitly offline, or when DNS,
TLS, or network access fails, use a fresh cache entry if available; otherwise
return `unavailable` and the plain link. Do not automatically retry on reconnect
or serve expired data. A network failure never changes the durable message,
Conversation, Run, or user-authored URL.

Clicking the plain link is a separate external navigation. Use an explicit
`rel="noopener noreferrer"` and `referrerPolicy="no-referrer"` on the original
user-authored external anchor; never replace it with metadata's canonical URL
or pass the local Conversation URL as a referrer. The no-referrer policy omits
the `Referer` header entirely
([W3C Referrer Policy](https://www.w3.org/TR/referrer-policy/#referrer-policy-no-referrer)).
The image `<img>` source, when present, is always the same-origin opaque media
route, not the remote URL.

## Dependency and license assessment

The lowest-risk initial dependency set adds no fetcher, HTML parser, sanitizer,
or frontend package. It should make one currently transitive URL dependency
explicit:

- Python standard library modules (`socket`, `ssl`, `ipaddress`, `zlib`,
  `gzip`, `html.parser`, and a carefully bounded URL component parser) are
  covered by the Python Software Foundation licensing information
  ([Python license](https://docs.python.org/3/license.html)). They still need
  security tests; standard library does not mean “validated URL” or “bounded
  network client.”
- Mentat already declares MIT in `pyproject.toml` and already pins
  `requests==2.33.0` and `Pillow==12.3.0`. Requests is Apache 2.0
  ([Requests license](https://github.com/psf/requests/blob/main/LICENSE));
  Pillow's upstream license is the MIT-CMU/PIL license
  ([Pillow license](https://github.com/python-pillow/Pillow/blob/main/LICENSE)).
- The URL policy above needs current UTS #46 nontransitional IDNA processing.
  `idna==3.18` is already pinned transitively in `uv.lock`; an implementation
  that imports it must promote it to an explicit runtime dependency rather than
  rely on Requests to keep bringing it. Upstream identifies it as BSD-3-Clause
  ([idna license](https://github.com/kjd/idna/blob/master/LICENSE.md)). This is
  a direct-dependency declaration, not a new parser or network stack.
- Reusing Requests' high-level defaults is not recommended for this security
  boundary. Its documentation says redirects are followed by default, cookies
  are supported, environment settings are trusted by default, and its timeout
  is not a total response-download limit ([Requests quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/),
  [Requests API](https://requests.readthedocs.io/en/stable/api/)). If Requests
  cannot be paired with a demonstrably pinned transport and `trust_env=False`,
  use a small direct transport built on the documented socket/TLS primitives;
  do not trade away pinning for convenience.
- Do not add BeautifulSoup, lxml, html5lib, Bleach, DOMPurify, a browser
  runtime, or an Open Graph scraping package for the first slice. The design
  never accepts or returns arbitrary HTML, so a full DOM/sanitizer does not
  buy a required capability. A future dependency would need maintained-source,
  CVE, native-code, size, and license review before adoption.
- No new frontend package is needed. The existing Next.js/React app should
  render the bounded projection with its current framework defaults; avoid a
  client-side fetcher and avoid external image URLs. If a future transport
  library is proposed, its license and explicit dial/pinning API must be
  recorded before implementation.

Pillow increases the attack surface because it processes hostile native image
bytes. Its security guidance should be treated as an operational acceptance
requirement: keep the pinned version current, hash-pin installation where the
packaging workflow permits, restrict formats, strip metadata, record bounded
failure classes, and isolate image decoding if the platform can do so without
weakening the local-first lifecycle.

## Representative public compatibility matrix

Live sites change behavior, geolocation, bot policy, and metadata without
notice, so this matrix is an opt-in dated smoke suite, never the deterministic
release gate. It records the normalized initial/final host, bounded outcome,
selected field presence, encoded/decoded bytes, duration, and whether an image
was safely transformed; it must not record raw query values, HTML, headers,
resolved IPs, or image URLs.

| Public URL | Compatibility represented | Acceptable observation |
| --- | --- | --- |
| `https://ogp.me/` | Canonical Open Graph vocabulary and structured image fields | `ready` with bounded OGP fields, or a recorded compatibility regression without policy relaxation. |
| `https://www.python.org/` | Conventional server-rendered site | `ready` from OGP or HTML title/description fallback. |
| `https://github.com/openai/openai-python` | Large commercial platform and repository page | `ready`, or bounded `unavailable` if rate/bot controls intervene; never cookie/auth escalation. |
| `https://developer.mozilla.org/en-US/` | CDN-backed documentation with redirects/localization | `ready` after at most three fully revalidated HTTPS redirects. |
| `https://news.ycombinator.com/` | Minimal HTML with little/no OGP | A title-only card or polished plain link is acceptable. |
| `https://www.youtube.com/watch?v=dQw4w9WgXcQ` | Media platform with anti-automation behavior | `ready` if ordinary HTML metadata is returned, otherwise bounded `unavailable`; no JavaScript/browser fallback. |

For reproducibility, maintain minimal synthetic fixtures for the tag patterns
observed in this matrix, not copies of third-party pages. A live observation
can justify a future compatibility ticket; it cannot justify widening an SSRF,
credential, MIME, redirect, byte, or image limit in place.

## Hostile-server and deterministic test matrix

All release-gate tests should run against a deterministic local fixture server
and injectable resolver/dialer. The fixture server should support HTTP/1.1,
TLS with a test CA, chunked responses, controlled compression, arbitrary
headers, delayed bytes, redirect graphs, and a request transcript. Tests must
assert that no request contains cookies, authorization, proxy authorization,
referrer, or a browser credential. The resolver/dialer seam must record the
validated IP, actual dial IP, TLS SNI, Host header, and redirect count.

| ID | Fixture / action | Expected result |
| --- | --- | --- |
| U1 | Normal absolute HTTPS URL; host case and explicit `:443`; fragment. | One canonical URL; fragment absent from fetch/cache key; one fetch. |
| U2 | Userinfo, raw/encoded backslash, controls, scheme-relative URL, non-443 port, `file:`, `data:`, `gopher:`, `javascript:`. | Blocked before DNS/connect; plain link remains. |
| U3 | IPv4 decimal, hex/octal-like, dword, IPv6, IPv4-mapped IPv6 spellings. | Canonicalize and classify; any non-global result blocked. |
| U4 | Unicode IDN, equivalent A-label, bad UTS #46 label, overlong label/host, one/two trailing dots, encoded reserved delimiters, path dot segments. | One canonical A-label/key for valid equivalents; malformed or ambiguous forms blocked before DNS. |
| D1 | Resolver returns loopback, unspecified, private, link-local, shared, multicast, documentation, benchmarking, unique-local, and reserved addresses. | Every unsafe address is rejected before connect. |
| D2 | Resolver returns one global and one unsafe A/AAAA answer. | Whole hostname blocked; no “safe answer” selection. |
| D3 | Resolver returns global at validation, then private on a second lookup. | Dial target remains the validated global IP; second lookup is not used. |
| D4 | Public-looking hostname with `.localhost`, `.local`, `.home.arpa`, `.test`, `.invalid`, or `.example`. | Blocked before network access. |
| D5 | Resolver returns 17 addresses; first pinned address fails; multiple addresses per family. | Over-limit answer is blocked; otherwise no more than one IPv6 and one IPv4 address from the one validated set are attempted. |
| P1 | Test TLS certificate is valid for hostname while socket is connected to a different injected IP. | Passes only when SNI/certificate hostname is correct and the dial target is the pinned IP. |
| P2 | Worker hangs in DNS, TLS, body read, HTML parse, or image decode and ignores cancellation. | Parent terminates/replaces it by the phase or 5.25-second watchdog; bridge remains responsive. |
| R1 | Relative 301/302/303/307/308 to another public HTTPS URL. | Followed with a new validation, up to three hops. |
| R2 | Redirect to HTTP, loopback, private IP, non-443 port, unsupported scheme, malformed or cyclic `Location`. | Blocked; no connection to the redirect target. |
| R3 | Four-hop chain or repeated normalized target. | Unavailable/blocked after the three-hop limit; no retry. |
| H1 | Valid `text/html` with `og:title`, `og:description`, `og:site_name`, `og:url`, `og:image`, structured fields, and `<title>`. | First valid bounded values projected; no raw markup; `og:url` neither changes navigation nor enters the payload/cache. |
| H2 | Missing OG tags but valid `<title>`/`description`; no metadata at all. | Useful fallback metadata where available; otherwise ready metadata is omitted and plain link remains. |
| H3 | Malformed HTML, duplicate tags, entity references, control characters, huge attributes, script/style payloads, XSS strings. | Bounded text only; no executable HTML; truncation and escaping are deterministic. |
| H4 | `text/html` with identity, gzip, deflate, Brotli, chunked, truncated, stacked, unknown, or corrupt content encoding. | Identity or one valid gzip within both byte limits may succeed; all others fail closed. |
| H5 | `application/xhtml+xml`, `application/octet-stream`, missing MIME, `text/plain`, HTML body with image MIME. | XHTML may parse; all other MIME/confusion cases use fallback. |
| H6 | UTF-8 BOM/header/meta, Windows-1252/ISO-8859-1, unknown charset, late meta charset, bidi controls, and C0/C1 controls. | Fixed charset precedence and sanitization are deterministic; unknown/late declarations cannot select an arbitrary decoder. |
| B1 | 512 KiB+ encoded page, 1 MiB+ decoded page, oversized headers, and misleading `Content-Length`. | Stop at the relevant bound without unbounded allocation. |
| A1 | Browser cookies, `.netrc`, proxy variables, provider credentials, client certificate variables, and a first-hop `Set-Cookie`; redirect to a recorder. | Recorder sees only the fixed header profile on every hop; no ambient value or returned cookie is replayed. |
| I1 | Valid JPEG/PNG/WebP; wrong extension; missing/incorrect image MIME; relative image URL. | Revalidate URL, verify bytes, re-encode only allowlisted formats. |
| I2 | SVG, GIF/animated WebP, TIFF, PDF, HTML image payload, truncated image, huge dimensions, decompression bomb, EXIF/GPS/PNG text metadata. | Image omitted or blocked; no external URL or unsafe bytes reach the browser. |
| I3 | Image redirect to private/HTTP, image over 2 MiB, image over 4 MP or 2,048 px. | Image omitted; metadata card may still be ready. |
| I4 | Call opaque image route with unknown ID, expired ID, URL-shaped ID, and an ID whose cache file is missing. | Bounded miss only; route never accepts/fetches a URL or exposes paths/hashes. |
| C1 | Same normalized URL through two messages; different query/path/fragment; same image URL under two pages. | Correct keyed-digest hits only; fragment does not fork; metadata/image namespaces do not collide. |
| C2 | `Cache-Control: no-store`, `no-cache`, `max-age=0`, `max-age=1`, `max-age=999999`, malformed/duplicate/conflicting `max-age`; `Expires`; `Vary: *`, fixed `Vary` dimensions, and absent cache headers. | Persistence and expiry follow the stated rules; malformed/conflicting freshness and `Vary: *` are not stored; `Expires` is ignored; fixed dimensions are represented by the request-profile version. |
| C3 | Cache entry from another data root/secret or mismatched policy, parser, transform, request profile, schema, or final URL digest. | Cache miss; no cross-root, cross-policy, or cross-target projection. |
| C4 | 513th metadata entry and transformed images crossing 64 MiB; process restart; backup/restore/export. | LRU bounds hold; cache may be discarded; no preview cache member enters a durable backup/export. |
| V1 | Rich previews disabled before enqueue, during pending work, and after cache expiry. | No new network work; existing plain link remains; no stale status claim. |
| V2 | DNS unavailable, network offline, TLS failure, timeout, connection reset, server never ends body. | Bounded `unavailable`; no automatic retry; cache-only read if fresh. |
| L1 | Fixed local minimal responses representing the public matrix's OGP, ordinary HTML, redirect/localization, title-only, and bot-block patterns. | Compatibility expectations are versioned without copying pages or depending on live network. |
| L2 | Run the optional dated public matrix above. | Observational signal only; never the sole release gate or permission to weaken a bound. |

The test suite should include a negative assertion that a browser-supplied URL
cannot select an arbitrary Python bridge capability or cause Node to forward
arbitrary headers. It should also verify message submission succeeds when every
preview test is made to fail.

## Recommendation and acceptance gate

Approve Slice 7 only as a read-only, capability-scoped implementation with the
defaults above. The implementation review should require:

1. a Python-owned fixed bridge capability keyed to canonical Message ID and
   revision, with no generic proxy parameters;
2. replaceable, credential-free Python workers with phase and hard wall-clock
   watchdog proof;
3. direct-pinning proof covering DNS rebinding, the complete A/AAAA set, SNI,
   `Host`, peer IP, and every redirect/image fetch;
4. bounded headers, encoded and decoded bytes, charset handling, explicit MIME
   allowlists, image pixels/dimensions/frames, and transformed output;
5. sanitized string-only projections and a URL-incapable opaque same-origin
   media route;
6. disposable private cache records with keyed/versioned identities, exact
   expiry/capacity, no-store handling, backup exclusion, and no raw URL logging;
7. the global opt-out, explicit cache clear, offline cache-only behavior, no
   automatic retry, and plain-link fallback;
8. the deterministic hostile-server matrix and optional dated public
   compatibility matrix above; and
9. dependency/license, IDNA conformance, and Pillow security evidence in the
   slice review log.

This is a best-effort OpenGraph capability, not a promise to render most of the
web. Sites that require JavaScript, authentication, cookies, HTTP image URLs,
unsupported MIME types, or larger bodies should receive a clean plain-link
fallback. Preserving that fallback is what lets Mentat improve compatibility
later without weakening its local-first security boundary.
