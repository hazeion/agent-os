# PR #281 dependency advisory repair

Exact base: `56e4baf734a0a2b1706b1d6fc7f80ce3ca82627e`.
Current Node foundation job 109786884537 in run 36684423913 passed its build
then failed the existing high-severity audit gate on older brace-expansion
and Undici locks. Replaying reviewed transitive pins exposed a newly published
critical Next.js advisory during current local validation.

## Final change

Pin Next and matching eslint-config-next 16.3.6, the minimum patched release
for GHSA-vcvr-r3jv-pc5j. Next env/eslint plugin and all eight optional platform
SWC artifacts follow exact 16.3.6 versions. Preserve reviewed brace-expansion
1.1.21, nested 5.0.12 and Undici 8.10.2 pins. The initial transitive portion is
exactly commit 5ffaf12: only version/resolved/integrity at three dev-only nodes.
The final combined scope additionally changes the two exact Next direct pins
and matching framework artifact metadata. Package-key graph and unrelated
versions remain unchanged; unrelated license-only npm refreshes were reverted.
Updated Next-family libc/license values are the registry's declared payload.
Parent minimatch ^1.1.7, nested minimatch brace range ^5.0.8 and jsdom ^8.9.0
admit the transitive patches; pinned Node 24.19 exceeds their minimum engines.

Official upstream advisory: https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j
It lists affected Next >=16.2.0,<16.3.6 and patched 16.3.6. Bounded app source
search found no next/og/ImageResponse usage. This limits direct reachability;
it does not remove the unchanged audit gate or justify keeping affected pins.
Original brace advisories: GHSA-q2hr-2g5m-vwhr, GHSA-qhr7-859c-m2p7 and
GHSA-6j4f-fj2g-mc7p. Completed hosted logs also named the known <=8.10.1
Undici advisory set. No audit severity threshold was reduced.

## Evidence

Frozen npm install and fresh audit pass with zero vulnerabilities. Full existing
lint/typecheck and 489 web tests pass with zero skipped/cancelled, followed by
a successful production build. Sixty-five Python private-bridge/preview plus
real built Project-context and Run-Inbox desktop/mobile browser methods pass
in 56.434 seconds; every fixture owns its ephemeral data root/process/profile,
and owner integrations remain inert. Both independent combined-package/lock
reviews are clear; the earlier 9-field-only verdicts are not the final scope.

No application, authentication, schema, workflow, diagnostic or public-archive
logic changed; no provider/model, owner service/configuration or credentials
were used. Exact repaired hosted-head acceptance remains pending after push.
