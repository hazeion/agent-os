# Disposable Caddy SSE drain fixture

PR #245's Linux Caddy job `109737727320` fails the disposable SSE drain-close
gate. The fake upstream sends persistent heartbeat comments every 100 ms.
Maintenance reload and its response check may queue several such comments;
reading one continuity heartbeat does not guarantee the next block is close.

Reproduced on the exact PR #245 base `8a2fe0254a0600938ff17f31b2669479d92cfa56`
with real pinned Caddy 2.11.4 amd64 on Linux. Before extracting only the regular
`caddy` archive member into an owned temporary directory, the probe verified
the lock's checksums, signature, certificate, archive and SBOM SHA256 digests,
the official archive SHA512, and the empty non-standard module inventory.
The previously verified supplied assets were reused without downloading or
installing anything. A caller generated only a disposable self-signed test
certificate/key in that directory. All listeners remained on loopback, and
the probe never read owner configuration or called a runtime/provider.

Adding 0.5 seconds of scheduling jitter immediately after successful maintenance
reload made the unchanged baseline fail in 1.777 seconds: the next drain block
was exactly `: keepalive\n\n`, rather than the close event. This is evidence of
queued fixture heartbeats, not evidence of a production Caddy drain failure.

The drain-only consumer now admits only exact heartbeat comments before the
unchanged `event: close\ndata: {"reason":"drain"}\n\n` frame, then requires
immediate EOF. Unknown events/comments, malformed close, early EOF and data
after close remain failures. The original 35-second budget starts before
maintenance publication/reload and is an absolute deadline shared by continuity,
drain, EOF and upstream-close verification. The existing three-second block
read budget remains; payload reads refresh only their remaining fixed budget
so a trickling line cannot extend it. No Caddy/profile config, production
service, event/header/auth/disconnect/reload gate or timeout was increased.

Validation on this exact base and diff:

- All 13 disposable-integration unit tests pass with the designated Windows
  Python and `-B`; six added tests cover queued comments, strict close/EOF order,
  malformed/unexpected blocks, missing close, expired budget, a trickling line
  and late EOF. `git diff --check` passes.
- All actual Linux Caddy gates pass with ordinary timing (2.005 seconds total).
  The shared-deadline reads were continuity heartbeat, exact close, then EOF.
- All actual Linux Caddy gates pass with the reproduced 0.5-second reload jitter
  (2.466 seconds), then again with exact block observation (2.456 seconds).
  The observed delayed stream delivered five exact heartbeat comments including
  continuity, then exact close and EOF. Each run used fresh disposable state,
  and cleaned only its owned Caddy child/backend and temporary files.

Independent reviews are required before publication. This record does not claim
the hosted CI job has rerun or passed yet.
