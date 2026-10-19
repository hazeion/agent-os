# Google session issuance

Scope: [Issue Google owner sessions from exact one-use login receipts](https://github.com/hazeion/agent-os/issues/253).
Baseline `bd72205`. No schema change, HTTP routes, enrollment or activation.

Python atomically validates and claims a verified receipt, rechecks exact
state/browser binding and current owner/configuration, then issues independent
cookie/CSRF secrets under the existing owner-wide cap and expiration policy.
Store digests only. Delete the receipt in the same transaction; replay or
response ambiguity cannot retrieve old secrets. No Google reauthentication or
fake device identity. Reject capacity exhaustion without evicting sessions.

Tests cover claims across connections, rollback, stale authority, wrong binding,
expiry, capacity, secret-free repr/storage, sign-out and SSE lease invalidation,
false step-up and a composed callback-to-session path. Two independent reviews,
fix/re-review until clean, then PR publication.

The existing authority had only sign-out-all. Added exact-session sign-out with
current method/generation and CSRF checks, a bounded secret-free audit and
post-revocation retention cleanup. Success auditing now commits with session
issuance rather than the intermediate identity-verification receipt. SessionGrant
repr omits cookie, CSRF and recovery material.

Both independent reviewers report no remaining findings. One additionally
verified the full 128-terminal-session boundary after single-session sign-out;
the new regression covers that boundary. The initial 62 combined tests passed.
The expanded run passed 63 checks and exposed one test-fixture error: old
passkey credentials had correctly aged out, so the history test now inserts
terminal Google sessions. All 10 final issuance tests pass, including real
private backup/restore and the retention boundary; the 54 unchanged auth,
transaction and owner-method regressions passed in the expanded run.

Wheel/sdist build, exact inventories and installed-wheel session API imports
pass. Windows path-normalized tracked-secret diagnostic found no new candidates;
ordinary Linux CI remains required. No HTTP cookie-delivery, active
network-stream closure or live Google acceptance claim. Status: review clean
and local verification complete; ready for PR publication.

September 22 CI follow-up: the Windows Python 3.13 webhook barrier tests timed
out during cold schema initialization before their cleanup block, leaving a
delivery worker alive at temporary-directory teardown. The tests now initialize
the real schema before measuring the barrier, use bounded synchronization
windows and release/join the worker even when the initial wait fails. All 19
webhook tests pass; two independent reviews are clean. Production webhook
timeouts and behavior are unchanged.
