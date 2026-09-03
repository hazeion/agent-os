# MDA-4C disabled Caddy profile review

Issue: #205  
Specification: #203  
Branch: `codex/mda-4c-caddy-profile`

## Scope

- Keep `remote-caddy-v1` disabled and isolated from every normal Mentat launch.
- Pin Caddy 2.11.4 release, signature, SBOM, architecture, and module inventory.
- Render one canonical HTTPS host with a literal loopback Node upstream.
- Exercise the real edge contract only inside an explicit disposable Linux run.

## Independent review

Two read-only defect-first reviews inspected the complete merge diff against
`main`. Their initial pass found deterministic CI entry-point failures, a dead
SSE route matcher, cancellation retention, inherited subprocess secrets, unsafe
parent traversal, incomplete forwarding assertions, and missing executable
SSE, listener, drain, and disk-rollback evidence. The first repair pass fixed
those findings.

The second pass found four remaining gaps: permissive disposable Caddyfile
inputs, unverified canonical TLS, incomplete SSE security-header assertions,
and ambient environments for system inventory tools. Those were repaired with
the shared canonical-host validator, quoted and control-free file paths,
certificate and hostname verification, exact fixed SSE headers, and fixed-path
credential-free `ss`/`ip` execution. Both reviewers then performed regression
passes and both returned `No findings`.

## Local verification

- 37 focused Caddy, CI workflow, CI quality, and Node foundation tests pass.
- All modified Python sources compile from text without writing bytecode.
- `python -m deploy.caddy.linux_harness --help` resolves the package entry point.
- `git diff --check` passes.
- The diff does not modify normal local launch code.

The first PR attempts caught five integration issues:
the reviewed release digests were absent from the secret-scan baseline, and the
formatter gate treated Caddy's unchanged context output as a formatting diff.
The baseline now records only those public release fingerprints, a normalized
full-repository scan reports no new candidates, and the formatter gate rejects
only actual added or removed diff lines. The exact generated profile also passes
Caddy 2.11.4 `adapt --validate` with a credential-free environment. The first
real edge request then proved Caddy's `permanent` shorthand emits 301; both
renderers now use the required explicit 308 status.
The next unknown-Host probe showed that the disposable HTTP site was host-bound
instead of catch-all like production; it now binds the ephemeral HTTP port and
uses the canonical matcher plus fixed 404 for every other Host.
The first capture then showed that combining delete and set operations for
Caddy's three special `X-Forwarded-*` fields marks them omitted. Those
conflicting overrides are removed: Caddy's untrusted-client defaults discard
the supplied values and generate all three replacements, while explicit
deletion remains for `Forwarded` and `X-Real-IP`. The capture gate still
requires the exact canonical replacements.
The first backend-crash probe then revealed a reusable HTTP/1.1 connection in
the fake upstream after its listener closed. Non-stream fixture responses now
close their upstream connection, so stopping the listener produces a real
unavailable-backend condition instead of allowing a pooled request through.

The complete local shard run is not accepted as evidence on this host because
machine-local Hermes executable ACLs, owner-only Windows ACL calls, and shared
restore state fail independently of this diff. The isolated GitHub matrix and
required real-Caddy Ubuntu job are the authoritative full-suite and Linux
behavioral gates.

## Activation boundary

This slice does not install Caddy, create production certificates, configure a
service or firewall, or expose a public listener. Those actions require a later
approved activation slice.
