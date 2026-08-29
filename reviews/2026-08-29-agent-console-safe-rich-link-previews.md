# Feature Slice Review: Agent Console safe rich-link previews

Status: Ready for publication
Slice: `agent-console-safe-rich-link-previews`
Date: `2026-08-29`
Review log: `reviews/2026-08-29-agent-console-safe-rich-link-previews.md`

## Slice contract

### Goal

Add best-effort rich previews for links in newly accepted user Messages while
keeping the plain external link immediate and permanent. Python alone owns URL
extraction, network policy, hostile I/O, parsing, image transformation, cache,
preference, and safe projection. Preview failure never changes Message, Turn,
Conversation, or Run authority.

### In scope

- Extract at most three candidate URLs from one exact accepted user Message,
  addressed only by canonical Conversation ID, Message ID, and Message revision.
  Browser and Node input cannot provide a URL, destination, headers, proxy,
  cache key, image source, runtime reference, or generic capability path.
- Normalize only absolute public HTTPS URLs on port 443 under the accepted URL,
  UTS #46, special-use-domain, IANA address, redirect, fragment, query-secret,
  and 2,048-byte rules from the accepted research.
- Resolve at most sixteen A/AAAA answers, reject the whole set if any answer is
  unsafe, choose at most one address per family, dial the validated numeric IP,
  preserve the canonical hostname for SNI and Host, and verify the peer address.
- Run hostile DNS, TLS, transfer, metadata parsing, and image decoding only in
  two replaceable credential-free workers. Enforce the one-second DNS phase,
  five-second operation deadline, and 5.25-second parent kill/replace watchdog.
- Support the fixed credential-free page/image request profiles, three fully
  revalidated redirects, bounded headers, identity/single-gzip page bodies,
  explicit HTML/XHTML MIME and charset policy, and one bounded metadata parser.
- Revalidate at most one image candidate. Accept only JPEG, PNG, or static WebP
  whose MIME, signature, and Pillow format agree; enforce 2 MiB, 4 MP, 2,048 px,
  one frame, metadata stripping, and a maximum 1,200×1,200 / 512 KiB WebP output.
- Store only sanitized derived data in an owner-private disposable versioned
  cache using a non-backed-up 256-bit HMAC secret, 512 metadata entries, 64 MiB
  transformed-image LRU, exact freshness rules, and opaque image IDs.
- Persist the global enabled-by-default preference separately with an exact
  revision. Disabling cancels/suppresses work and cards; clearing cache does not
  change the preference; re-enabling does not refetch old Messages automatically.
- Add fixed Python bridge and same-origin Node capabilities for exact Message
  preview enqueue/read/retry, preference read/update, cache clear, and opaque
  image reads. Binary responses are fixed WebP and never fetch on miss.
- Render inert public-HTTPS anchors with `noopener noreferrer` and no referrer,
  plus asynchronous pending/ready/unavailable/blocked/disabled card states
  keyed by Conversation, Message, revision, and candidate ordinal. Plain links
  remain useful in every state.
- Promote `idna==3.18` to an explicit runtime dependency. Add no fetcher,
  sanitizer, DOM parser, or frontend package.

### Out of scope

- Browser-side or Node-side remote fetching, browser credentials/cookies,
  Requests defaults, environment proxies, automatic redirects/retries,
  JavaScript execution, arbitrary HTML, remote images, HTTP links/images,
  authentication, screenshots, oEmbed, video/audio, or full DOM parsing.
- Fetching drafts, pasted-but-unsent text, assistant Messages, cancelled or
  changed Messages, startup history, newly paginated history, or Messages after
  re-enable without explicit retry.
- Raw URLs outside canonical Message text; raw HTML, headers, redirects, IPs,
  DNS answers, cookies, server banners, image URLs, cache digests, file paths,
  internal errors, or secrets in cache records, logs, audits, metrics, Node, or
  browser payloads.
- Treating preview cache as Conversation authority, attachment/artifact storage,
  backup/export content, or a reason to add a Mentat schema migration.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Candidate extraction and canonicalization accept only the fixed public-HTTPS subset and never turn browser input into a URL oracle. | URL/IDNA/query/path/message-binding unit tests. | Passed |
| AC-2 | DNS rebinding, mixed/over-limit answers, special-use names, every IANA non-global class, numeric pinning, SNI/Host, peer verification, and redirect revalidation fail closed. | Injectable resolver/dialer and hostile TLS server tests. | Passed |
| AC-3 | Workers inherit no credentials or private authority and are killed/replaced at every stuck phase without blocking the bridge. | Environment/FD/phase/watchdog/process-tree tests. | Passed |
| AC-4 | Header, encoding, byte, MIME, charset, parser, metadata, and redirect bounds are exact; raw HTML never crosses. | Deterministic hostile HTTP fixtures H1–H6, B1, R1–R3, A1. | Passed |
| AC-5 | Only verified static JPEG/PNG/WebP becomes a bounded metadata-stripped WebP behind an opaque same-origin ID. | Image matrix I1–I4 and binary route tests. | Passed |
| AC-6 | Cache identities, freshness, negative caching, LRU, secret/root/version isolation, preference revisions, offline behavior, clear, restart, backup, restore, and compatible export are exact. | Cache/preference C1–C4 and V1–V2 tests. | Passed |
| AC-7 | Message submission remains independent; asynchronous cards and permanent plain links handle ready, pending, disabled, blocked, unavailable, retry, tab switching, pagination, and stale revisions accessibly. | Bridge/BFF/Home/renderer interaction and browser tests. | Passed |
| AC-8 | Full Python/web/build/browser gates, optional dated public compatibility observations, dependency/license evidence, and two adversarial re-reviews pass. | Final verification record. | Passed; CI pending |

### Fixed limits

The implementation uses the accepted defaults without relaxation: three URLs,
2,048 canonical bytes, HTTPS/443, three redirects/four requests, one-second DNS,
five-second operation, 5.25-second watchdog, sixteen answers/two connection
attempts, two-second connect/TLS, one-second idle read, 32 KiB/64/8 KiB headers,
512 KiB encoded and 1 MiB decoded page, 2 MiB image, 4 MP / 2,048 px input,
1,200 px / 512 KiB WebP output, 24-hour ready maximum, five-minute unavailable,
one-hour blocked, 512 metadata rows, 64 MiB images, and two workers.

### Scope discussion and approval

- GitHub issue #139 and the accepted research issue #130 define the scope and
  safety gate. The user granted standing approval for all remaining slices and
  explicitly approved parallel agents for bounded packages within a slice.
- Approved at: 2026-08-28 conversation; parallelization confirmed 2026-08-29.

## Test strategy

| Package | Planned evidence | What it proves |
| --- | --- | --- |
| URL/IP policy | Table-driven U1–U4 and D1–D5 across Python 3.11–3.13. | Parsing differences cannot widen the destination set. |
| Transport/workers | Test CA, resolver/dialer transcript, redirect graph, fixed headers, phase hangs, kill/replace. | Validation and actual connection are the same credential-free operation. |
| Metadata/image | Synthetic bounded HTML, encodings, MIME confusion, gzip bombs, hostile images, metadata inspection. | Hostile bytes become bounded strings/clean WebP or no preview. |
| Cache/preference | Secret/version/root isolation, expiry clock, LRU limits, restart, disabled/offline/clear, backup/export exclusion. | Derived state stays disposable, private, bounded, and policy-correct. |
| Bridge/BFF/UI | Exact-ID bodies, extra-field rejection, byte caps, stale revisions, asynchronous card state, anchors, accessibility, pagination, failure independence. | Browser cannot select network work and Message authority is unchanged. |
| Integrated gates | Focused tests, full suites, production build/performance, desktop/mobile browser, two adversarial reviews. | The complete capability is safe and usable across supported platforms. |

### Test discussion and approval

- Standing approval covers the strategy. Deterministic injected fixtures are the
  release gate. The dated public compatibility matrix is observational only and
  cannot relax policy or be the sole evidence for any criterion.

## Parallel work plan

After this contract is frozen, independent packages may proceed in parallel:

1. pure URL/IDNA/special-use/IP policy and table-driven tests;
2. disposable cache, preference, freshness, and eviction tests;
3. bounded HTML metadata parser fixtures;
4. image verification/re-encoding fixtures;
5. frontend anchor/card rendering against static safe projections.

Pinned transport/worker supervision, canonical Message service, Python bridge,
Node BFF, and Home integration follow in that order. `server.py`,
`mentat/local_bridge.py`, and `home-console.tsx` each retain one integration
owner to avoid shared-file races.

## Implementation record

- Added pure URL/IDNA/special-use/IP policy with source-controlled IPv4/IPv6
  deny tables, whole-answer validation, and two pinned connection candidates.
- Added a direct socket/TLS HTTP/1.1 transport with numeric dialing, hostname
  SNI/Host, peer verification, fixed credential-free headers, redirect
  revalidation, bounded headers/chunking/content lengths, gzip limits, MIME
  handoff, idle reads, and one monotonic operation deadline.
- Added two persistent replaceable stdio workers with an allowlisted environment,
  no inherited descriptors, phase messages, one-second DNS and 5.25-second
  parent watchdogs, bounded protocol lines, capacity failure, and shutdown.
- Added bounded HTML/XHTML charset and metadata parsing plus verified static
  JPEG/PNG/WebP transformation into metadata-free bounded WebP.
- Added the owner-private HMAC cache, opaque images, exact expiry/LRU bounds,
  cache schema/row validation, corrupt-cache discard, independent revisioned
  privacy preference, and explicit clear behavior.
- Added exact Message/revision service admission, at most eight pending jobs,
  stale/disable/clear generation gates, negative caching, offline cache-only
  reads, no automatic retry, and explicit retry.
- Added fixed Python bridge and Node BFF JSON/image capabilities, same-origin
  routes, strict safe projections, and browser clients with no URL input.
- Added protected HTTPS anchors, bounded asynchronous cards, opaque same-origin
  images, retry, enabled-by-default privacy disclosure, disable, and clear UI.
  Message submission and permanent text/link rendering stay independent.
- Promoted `idna==3.18` to an explicit BSD-3-Clause runtime dependency. No
  fetcher, HTML/sanitizer, DOM, image, state, or frontend dependency was added.

## Verification

- 61 focused Python policy/cache/parser/image/transport/worker/service tests
  passed; 92 focused bridge/server/backup/export tests and 34 packaging tests
  passed with loopback permission where required. The 1,722-test full run found
  one missing public-module allowlist entry; after the fix, that test and the
  complete packaging suite passed.
- 154 web tests passed with clean lint and typecheck. The production webpack
  build passed with all fixed preview routes.
- The tracked-file secret scan passed after test-only credential-shaped URL and
  environment fixtures were split into inert components.
- The first Windows matrix exposed that regular files may report link count
  zero and do not expose POSIX mode bits. The validator now accepts only zero
  or one on Windows, still rejects hard links, and has a platform regression
  test; POSIX-only mode assertions no longer make false Windows claims.
- The production performance gate now warms the complete fixture once, then
  scores seven unchanged samples with 200 rows, three preview cards, and one
  image card. It passed at 127.6 ms accepted dispatch, 18.9 ms loaded tab,
  9.3 ms optimistic paint, 7.0 ms stream paint, and zero typing requests.
- In-app browser at 1440×900 and 390×844 verified the ready card, permanent
  protected external link, full privacy disclosure, 34 px closeable tabs, no
  redundant Active label, zero center delta, directional rail arrows, 44 px
  mobile preview actions, and zero page overflow. Mutating retry/clear paths
  remain covered deterministically rather than causing browser-side disclosure.
- Optional 2026-08-29 public compatibility observations through the isolated
  worker: OGP, Python.org, and title-only minimal HTML were `ready` in 916 ms,
  154 ms, and 199 ms; one OGP image transformed to a 4,248-byte WebP in 456 ms.
- Backup and schema-5 compatible export exclusion tests passed for cache,
  images, secret, and preference. Packaging/dependency tests passed (36).

## Adversarial review

- Two independent read-only adversarial reviews completed after iterative
  fixes. The final safety and frontend re-reviews reported no findings.

## Documentation updates

- Updated `AGENTS.md`, `ARCHITECTURE.md`, and `CHANGELOG.md` with the Message,
  worker, transport, cache, privacy, projection, and plain-link contracts.

## Publication gate

- Standing authorization recorded. Local implementation gates are complete;
  ready-PR CI and merge evidence remain pending.

## Outcome review

- Classification: Ready for publication.
