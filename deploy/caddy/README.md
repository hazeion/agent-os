# Disabled Caddy deployment profile

`remote-caddy-v1` is a Linux-only future deployment profile. It is deliberately
not connected to `mentat start`, `run.sh`, `run.bat`, the preview supervisor, or
any service unit. Nothing in this directory downloads Caddy, creates a
certificate, opens a listener, changes a firewall, or reads a bridge token.

The checked-in lock pins Caddy 2.11.4 Linux amd64 and arm64 release assets,
SBOMs, detached signatures, and the official signed checksum material. Before
any future extraction, an approved root-owned activation must verify the
checksum signature with Cosign, then call `verify_downloaded_release` on a
staged, regular-file-only asset directory. Its custom-module gate expects the
exact empty output of `caddy list-modules --skip-standard --versions`.

`linux_harness.py` runs a parser-only gate by default. Its explicit
`--run-disposable --test-cert FILE --test-key FILE` mode invokes
`disposable_integration.py` against only ephemeral `127.0.0.1` ports. It
captures the real upstream request after forged forwarding headers, exercises
TLS/SNI/Host, canonical HTTP redirect, fixed 404, SSE headers/frames, failed
reload with atomic disk rollback, no-store maintenance reload, bounded SSE
drain/cancellation/reconnect/closure behavior, exact TCP/UDP listener inventory,
external-address isolation, known-good recovery, and backend crash/restart. It
refuses to create, obtain, or persist TLS material: a CI namespace must inject
a disposable certificate and key. Production activation, including real public
listener and firewall configuration, remains a later approval.
