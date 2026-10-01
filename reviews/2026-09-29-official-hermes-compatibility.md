# Official Hermes release compatibility

The owner selected the updated official NousResearch Hermes agent over their
fork. Stage official stable `v2026.9.24` (Hermes 0.21.5) at
`f97608f178d1ffeca59860195ab7da295f7c8e5f`, then verify Mentat's fixed supported
integration before selecting it. Preserve the existing fork and private owner
state for recovery. This scope does not change upstream source or qualify
Project execution merely from a successful upgrade.

Official stable retains provider inventory and disabled-skill signatures but
moves the supported profile-model writer from `hermes_cli.web_server` to
`hermes_cli.web_routers.profiles`. Its first three parameters remain
`profile_dir`, `provider`, `model`; the official fixed model route invokes the
same helper with validated profile selection and mutation locking.

Mentat inventory and confirmed mutation now use the same fixed current owner.
The owner explicitly requested no legacy writer fallback. Missing modules,
dependencies, initialization failures or missing writers fail closed; older
installs retain safe inventory but cannot advertise or mutate model switching.
Browser input cannot select a module, executable, path or fourth argument.
All existing authenticated-inventory, exact preview/confirmation, active-Run
lock, verification and rollback contracts remain in place.

Verification: real Python import-path fixtures for current owner support and
older owner refusal,
missing dependencies and incomplete new modules; existing provider-switch,
profile/registry and HTTP safety regressions. Inspect official source signatures
and run credential-free probes against the staged release. Obtain two
independent code reviews, fix findings, then publish a full PR. Select the
official runtime only after private backup and active-work/lifecycle checks.

The fresh upstream audit also identifies supported Run API, Subagent Lifecycle,
`ctx.llm`, provider-plugin, supervision and egress-proxy seams. Their exact
profile/call/retention/containment guarantees must be mapped before replacing
fork-specific remote enhancements. Unsupported features stay unavailable.

Verification evidence: official stable is installed side-by-side with the fork
using `uv sync --locked --extra all` on Python 3.13.14; dependency verification
reports 103 compatible packages. Credential-free real-runtime probes confirm
inventory/skill/model-writer signatures and Mentat's exact revised writer
selection. A disposable home successfully exercises Mentat's fixed local
control startup, session creation and owned-process shutdown with zero model
submissions. These staged probes preceded the backup/lifecycle activation step.

All 32 focused provider-switch/profile/runtime-switch tests pass. Independent
review found a fallback ambiguity; the owner's no-fallback preference removes
that selection path entirely. Same-name/broken-package regressions remain to
prove unsupported implementations never call an old writer. Final no-fallback
code received both independent re-reviews with no remaining findings. The final
stock-only import also passed the real credential-free official-release probe.

Host activation completed after two independent operator-script reviews,
validated owner-private backups, and exact live authority/quiescence checks.
The selected CLI, fixed canonical Python discovery, and supported gateway
service now resolve to the pinned official release. Gateway health verifies
its live PID, zero active agents, and a loopback API listener. No automatic
fork fallback exists. The previous checkout remains available for deliberate
operator recovery.

Official CLI startup upgraded a stock default soul template and relocated
older configuration backups; hash checks verified the relocated copies.
The original backup remains retained, and a fresh backup validated the resulting
state before activation. The readiness audit uses the precise gateway snapshot,
because the textual CLI status command itself updates logs and skill metadata.

The host received only the reviewed two-file compatibility backport; 33 focused
provider/profile/creator regressions passed there. With the required Node runtime
installed, the local Next.js dashboard returns HTTP 200 and its dashboard/bridge
listeners remain loopback-only. The host's legacy lifecycle status report
initially omitted the verified live listener; HTTP/socket readback established
activation evidence. The later [POSIX inventory fix](2026-09-29-posix-listener-inventory.md)
diagnosed partial successful tool output and verified actual host status after
its reviewed backport, without restarting the dashboard.
This does not establish live model execution, authenticated off-network Mentat
access, or qualified Project-worker admission.
