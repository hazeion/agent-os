# Google owner setup and recovery

Scope: [Host-admin setup through a setup-only gateway](https://github.com/hazeion/agent-os/issues/256).
Baseline `1890151`. The complete slice must include a usable CLI/browser proof
ceremony; a disconnected authority helper or printed OAuth URL is insufficient.

Design review identified an integration dependency: Google's fixed callback
requires canonical HTTPS, while the ordinary gateway remains local-only and
the Caddy profile is disabled. Implement separate, narrow setup ingress with
only fixed setup/start/callback/completion routes, bounded requests and no
dashboard or generic bridge. Use explicit host-admin grants, one immutable
candidate, and exact CLI confirmation before ownership changes.

Reserve stopped-server ownership under the shared lock, release the lock while
waiting externally, and make normal startup reject an active setup reservation.
Preserve prior authority through timeout/cancel/crash; confirm under the lock
with generation/configuration/candidate/expiry checks, a validated backup,
revocation and recovery-material rotation. Normal website login is the separate
required [Google sign-in UI](https://github.com/hazeion/agent-os/issues/257).

Implementation starts with the pure setup ingress contract and tests, then
reservation/authority, setup gateway and CLI integration. Full disposable TLS
and CLI tests plus two independent reviews are required before publishing the
completed slice. Real Google/domain acceptance remains a separate evidence gate.
Status: in progress; no activation or completion claim.

Initial setup ingress renderer limits methods/routes, rejects cleartext rather
than redirecting callback queries, and discards both runtime and access logs.
Checked syntax against Caddy's official request_body, handle, log and global
servers documentation on September 21–22. Thirteen pure setup/existing-profile
checks pass. Actual pinned-binary adaptation and disposable TLS request tests
remain required; string-level checks do not establish working ingress.

The first setup reservation implementation reuses the normal server's lifetime
reservation path under the same cross-process private mutation lock. It adds
an exact purpose/nonce/expiry record; ordinary release cannot delete it, and
setup transitions recheck its exact ownership and deadline. Seventeen focused
reservation/setup/existing-profile checks pass. This is incomplete integration:
package inventory, actual Caddy parser/TLS tests, gateway capabilities, authority
confirmation/backup/recovery and CLI teardown were the next integration work.

September 22 integration evidence:

- The actual Node/Python grant and callback flow reaches a private candidate;
  host CLI confirmation performs real backup and owner commit. End-to-end fake
  provider tests cover enrollment and recovery, including old-session revocation.
  Expiry and injected rotation failure preserve prior authority.
- Both pinned Caddy/Cosign release verification and real Linux disposable TLS
  gates passed. Setup routes/header replacement, blocked data paths and separate
  form/callback referrer policies are exercised with the actual binary. No
  public listener or ACME certificate was used in those tests.
- Review found CSP blocked the form redirect to Google; both layers now permit
  the fixed authorization origin. Real Chromium with intercepted Google traffic
  passes the old-policy negative control and successful current-policy redirect.
  That browser test also exposed Origin:null under form no-referrer policy;
  only the form uses same-origin policy, while callbacks remain no-referrer.
- Review found terminal termination could orphan ingress. CLI handles terminal
  signals, and pipe-watching guardians own the listener group. A further review
  caught guardian death leaving a separate child group; they now share the group
  and teardown verifies its disappearance. Actual Linux parent-crash, guardian
  SIGKILL, SIGTERM and SIGHUP tests pass, checking child reaping/listener closure.
- The latest focused suite passed 61 tests. The real-backup enrollment/recovery
  flow and expanded authority failure cases passed seven additional checks.
  Package build/inventory passed before the final guardian changes; a final
  rebuild and whole-slice independent reviews remain required before PR push.

Normal website sign-in and real-operator Google acceptance remain open. The
single CLI uses supplied certificate/key and release assets; deployment setup
is not silently performed for the operator.

Final verification: the combined setup/CLI/authority/packaging regression suite
passed 100 tests. The actual Chromium CSP control and Google-redirect test
passed; all real Linux Caddy setup/previous-profile gates and guardian-death
cases passed. Final wheel/sdist inventories and installed gateway asset,
deployment lock and CLI imports verified. A Windows path-normalized secret
diagnostic found no new candidates; ordinary Linux CI remains required.

Both independent whole-slice reviews are clean after the recorded fixes. The
ignored operator guide was explicitly staged so published documentation links
resolve. Status: local verification and review complete; ready for PR push,
with CI/merge and later real-provider/website acceptance still open.

## CI reconciliation after publication

PR 258 exposed stale exact package assertions in nine matrix jobs after the
intentional addition of `deploy`, `deploy.caddy` and the setup gateway asset.
The expected sets now match those public payloads; private/test exclusions stay
intact. A Windows Conversation route test also performed cold schema migration
inside its HTTP deadline and removed its directory while a request could still
own SQLite. It now initializes schema first and keeps the patched data root and
directory alive until non-daemon request workers finish in teardown. No
production behavior or timeout changed.

All 66 affected quality/bridge tests pass locally. Independent authority and
gateway reviewers both report no concerns with these corrections. The separate
Node-foundation Agents-unavailable CI failure lacks enough diagnostic evidence
to identify whether it was a bridge deadline or registry unavailability; it is
not claimed resolved by these test fixes.
