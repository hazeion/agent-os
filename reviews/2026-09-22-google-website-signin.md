# Website Google sign-in and authenticated access

Scope: [Website Google OAuth sign-in](https://github.com/hazeion/agent-os/issues/257).
Baseline `59126f8`. Deliver the visible Continue with Google page and complete
server-side callback/session/sign-out flow, with authenticated documents,
operations, artifacts and live streams. Preserve local mode. A static button
or a route check only at stream creation is not completion.

Design review requires process-owned canonical HTTPS mode, exact manifest
admission, a small anonymous asset/login allowlist, and Python revalidation on
each private data operation. Cookie/CSRF headers come only from validated
request context, never a browser-selected bridge target. Existing mutation
clients must include session-bound CSRF. Stream leases must be revalidated
before protected reads and emissions without extending session idle expiry,
and released on every termination path.

Keep enrollment/recovery host-only. Reuse the browser-tested CSP/form referrer
policy from setup. Callback responses must remove query material and show only
bounded error states; no provider response or arbitrary return URL is rendered.
Whole-slice independent reviews and fixes until clean precede PR publication.
Status: implemented; two independent whole-slice reviews found no remaining
implementation defects after the correction loop. Ready for PR publication;
remote website activation and real provider acceptance remain unverified.

## Verification

- Final TypeScript and ESLint checks pass; all 386 web tests pass.
- Final focused Python regression passes 136 tests across owner authority,
  transactions/session issuance, private bridge admission, lifecycle, packaging
  and Caddy profile contracts.
- Production Next.js build and standalone preparation pass. Fresh wheel and
  source archive pass exact inventory/integrity verification. An isolated wheel
  install imports the owner website modules and contains the built sign-in,
  callback and session-script assets.
- Built-site Chromium tests exercise synthetic Google success, cancellation,
  expiry, wrong account, provider outage, secure cookies, missing-CSRF rejection,
  two browser sessions, individual sign-out and all-browser revocation. Mobile
  and desktop sign-in screenshots were inspected. No live Google account was
  used; the fixture intercepts provider traffic.
- A real built-site HTTP stream test verifies revocation during streaming,
  no subsequent private disclosure, lease cleanup and unchanged idle expiry.
  Concurrent request-context tests verify isolation between browser sessions.
- Real Linux signed-Caddy checks pass for the owner website profile, including
  forwarding/header stripping, TLS routing and form/callback referrer policy.
  Linux guardian tests cover parent crash, signals, descendant listener cleanup
  and safe repeated stopping. These use disposable loopback fixtures, not a
  public deployment.

Independent reviews: `setup_authority_review` and `setup_gateway_review` both
reported clean whole-slice findings. Final packaging checks then passed.

Real operator Google-client enrollment, configured public DNS/TLS and the full
owner-host acceptance remain open under the activation parent. This evidence
does not qualify a real provider account or close the complete garage journey.
