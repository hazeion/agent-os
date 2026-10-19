# Public page reading prerequisite

Implement one private, fixed public HTTPS page-read component for the approved
Project research boundary. Reuse the existing URL/IP/pinned-TLS/header/redirect
policy; preserve link-preview page/image behavior. Research reads use fixed GET,
no credentials/cookies/referrer/proxy, at most three revalidated redirects,
ten-second transfer and two-MiB encoded/decoded bounds. No arbitrary methods,
headers, caller transport, images, provider selection or browser fetch route.

Bound article/plain-text extraction to 64 KiB, title and link labels to fixed
sizes, 32 normalized public HTTPS link candidates, finite tags/attributes and
depth. Script/style/template/embedded/form content stays omitted; raw HTML is
never returned or executed. Returned links are candidates, not verified fetches
or authority. Mark text truncation explicitly; a reader cannot claim an entire
source was returned. Treat all website text as untrusted evidence.

Use two dedicated replaceable credential-free processes with fixed commands,
one-second DNS and 10.25-second total watchdogs. Pass only a bounded normalized
public URL and request ID, never Project instructions, root paths, credentials,
private context, Console descriptors or provider variables. Reuse existing
owned process/Job termination mechanics and add finite worker resource limits
where supported. Failure/replacement is not automatic request resubmission.

This is a transport/parser prerequisite, not a complete broker or execution
capability. It grants no Run, approval, work budget, public-search provider,
Hermes tool or generated-output authority. Production integration remains
unavailable until exact approved public input, durable work reservation,
Run/scope/epoch fencing, qualified tool inventory and artifact provenance pass.
The whole Agent worker retains its separate filesystem/network isolation; do
not claim this trusted network utility hides every host file from its process.

Verify hostile URLs/DNS/redirects/peer substitutions, gzip/chunk/header bounds,
malformed/deep HTML and charsets, secret-free fixed requests, bounded candidate
links/text, process environment, watchdog/replacement/descendant cleanup and
actual public TLS without any provider. Verify package contents, obtain two
independent reviews, fix/re-review, then a full PR. No live model or owner
service/configuration change is part of this slice.

The final combined reader/parser/transport/shared-preview group passes all 42
actual Linux tests with no skips. Windows passes 30 portable methods with 12
Linux-only skips. Real public TLS retrieval of Python documentation returns
1,348 bytes of normalized text and 32 candidate links, without truncation or a
model call. This is public transport evidence, not garage or Agent acceptance.

Independent reviews found startup failure leaks, unverified cleanup ownership,
replacement/close races and buffered-result publication after close. The shared
slot now serializes lifecycle admission/publication, cleans initial and
replacement startup failures, retains/fences unverified ownership, and joins
owned reader threads. Both pool constructors retain earlier successful slots
on partial failure; close attempts every slot before re-raising even a raw
error, preserving ownership for explicit recovery. Slot and both pool success
publications respect completed close. Controlled mocks and actual Linux
process/thread regressions cover these findings. Both final independent
read-only reviews are clear; no existing preview network limit was widened.
Twenty existing Windows preview service/server/bridge tests also pass. Final
wheel/sdist exact public inventory and RECORD verification pass; six isolated
installed modules match the final source bytes, and installed parser/worker
command checks pass. No runtime/provider readiness is implied by packaging.
