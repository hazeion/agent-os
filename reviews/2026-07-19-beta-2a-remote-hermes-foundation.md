# Feature Slice Review: Remote Hermes Connection Foundation

Status: Local verification and two adversarial reviews cleared; publication and hosted CI pending
Slice: `beta-2a-remote-hermes-foundation`
Date: `2026-07-19`
Review log: `reviews/2026-07-19-beta-2a-remote-hermes-foundation.md`

## Slice contract

### Goal

Establish the first safe Milestone 2 boundary: Mentat can preview, verify, and
persist exactly one local-or-remote Hermes connection selection, keep the API
credential exclusively in owner-only server storage, and derive bounded trusted
readiness/capability metadata from fixed authenticated Hermes API paths.

### In scope

- One versioned connection record below the external data root's owner-only
  `private/` directory, with atomic replacement, a shared private-state lock,
  strict schema validation, and a new binding identifier whenever endpoint,
  mode, or credential changes.
- Exact preview and confirmation operations bound to both the current record
  and the proposed mode, endpoint, label, and credential without returning the
  credential or its digest.
- Explicit `local` selection and one `remote` origin. Remote origins reject URL
  credentials, fragments, queries, non-root paths, invalid ports, and cleartext
  transport except explicit loopback development origins.
- A server-only HTTP client that uses fixed health/capability paths, standard
  certificate and hostname verification, bounded timeouts and bodies, no proxy
  environment, no redirect following, and bearer authentication only on the
  authenticated requests.
- Public health as untrusted liveness only. Trusted remote state comes from
  validated authenticated detailed-health and capability responses and is
  reduced to an allowlisted, secret-free summary.
- Loopback-only API routes for reading the safe summary, previewing a change,
  confirming an exact change, and testing the currently selected remote.
- Focused safety/compatibility tests, canonical contract and operator docs,
  two independent adversarial reviews, full local verification, hosted CI,
  publication, merge, and outcome review.

### Out of scope

- Routing Console, sessions, runs, approvals, Context Packs, images, profiles,
  Kanban, cron, provider/model administration, or any mutation through the
  remote endpoint.
- A transport-neutral adapter, remote Settings UI, credential migration from
  Hermes, general secret management, custom certificate authorities, insecure
  TLS overrides, redirect support, arbitrary URLs/paths, SSH, or filesystem
  access to the remote host.
- Claiming active-profile inventory or full remote parity where the approved
  authenticated upstream capability is still absent.
- Putting the connection record or API credential into general backups,
  diagnostics, logs, tracked fixtures, browser storage, or browser responses.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | One strictly validated local/remote record is atomically stored as an owner-only private file; unsafe, linked, broad-permission, oversized, or newer-schema records fail closed. | Storage and filesystem adversarial tests | Complete |
| AC-2 | Preview/confirmation binds the current record and complete proposed secret-bearing intent; stale state, changed input, wrong credential, or reused confirmation fails without mutation. | Preview/confirm concurrency and negative-path tests | Complete |
| AC-3 | Remote URL validation permits one normalized origin only and rejects embedded credentials, query/fragment/path injection, invalid schemes/ports, and non-loopback cleartext. | Table-driven URL tests | Complete |
| AC-4 | The client uses fixed paths, verified TLS, bounded requests/responses, no environment proxy, no redirects, and never sends bearer auth to public health. | Injected transport tests and TLS/redirect/error cases | Complete |
| AC-5 | Only authenticated, schema-valid detailed health and capabilities authorize a trusted connection summary; unknown schemas/auth/platforms and unbounded or secret-shaped upstream data fail closed without raw details. | Discovery schema, redaction, auth, size, and malformed-response tests | Complete |
| AC-6 | Browser-facing responses return only mode, the operator-supplied public label, opaque binding, minimized status/version/model/readiness/capability names, and bounded error codes; stored authority and unminimized upstream data are never returned. | Route and recursive secret-absence tests | Complete |
| AC-7 | Local mode remains the default and performs no network request; changing a selection creates a different binding so later endpoint-bound state cannot cross connections. | Default/no-network and binding tests | Complete |
| AC-8 | Focused/full/static checks, supported hosted matrix, documentation, and two independent adversarial reviews clear on the final diff. | Verification log and CI | Pending |

### Constraints and recovery

- Safety: the browser supplies a credential only in an explicit same-origin
  confirmation request; Mentat never echoes, logs, caches, or stores it outside
  the owner-only record. All public failures are bounded codes/messages.
- Compatibility: Python 3.11-3.13 and macOS/Windows/Linux behavior must use only
  the standard library and existing project storage primitives. Existing local
  Hermes execution remains unchanged.
- Rendered behavior: no visible UI is added in this foundation slice; API
  behavior is contract-tested and Settings UI remains a later slice.
- Rollback or recovery: select `local` through the same preview/confirmation
  path. A failed verification or failed atomic commit preserves the previous
  selection. The secret is intentionally excluded from ordinary backups.
- Documentation targets: `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`,
  `ARCHITECTURE.md`, `DATA_LAYOUT.md`, `README.md`, and `CHANGELOG.md`.
- README voice: preserve a quick, beginner-friendly installation front door
  with light, concise language for a solo developer who wants agents to help
  organize projects and tasks in a pleasant web UI. Keep detailed security and
  architecture explanation in the linked canonical documents.
- Version-control strategy: branch
  `codex/beta-2a-remote-hermes-foundation` from merged `main`; ready PR to
  `main`, squash merge after exact-head hosted CI.

### Scope discussion and approval

- Recommendation and rationale: implement the first approved
  `REMOTE_HERMES.md` implementation-order group as one coherent foundation.
  Storage without verification would persist unusable authority; a client
  without durable selection would have no safe origin or credential boundary.
- Alternatives considered: environment-only secrets would not satisfy durable
  owner-only operator storage; generic `urllib` calls could honor ambient proxy
  settings and accept arbitrary paths; direct browser-to-Hermes calls would
  expose the credential and require remote CORS; routing Console now would skip
  the required transport-neutral boundary.
- User decisions: standing authorization directs completion of each roadmap
  milestone through bounded reviewed slices and approves publication/merge
  after two zero-finding reviews and passing gates. README changes must remain
  first-user friendly, quick to scan, and concise.
- Approved at: `2026-07-19` through standing authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No remote connection storage exists. | Create/read/replace plus permission, symlink, hardlink, oversize, malformed, and forward-version tests. | The credential has one fail-closed owner-only authority. | Native Windows DACL behavior receives final proof in the hosted Windows matrix. |
| AC-2 | No connection mutation workflow exists. | Exact preview token, input change, state race, probe failure, and commit failure tests. | Confirmation cannot reuse stale or different authority. | Does not yet bind Console state because no remote Console exists. |
| AC-3 | The approved URL rules are documentation only. | Table-driven IPv4/IPv6/DNS/IDNA and injection cases. | Only one normalized operator-granted origin can be selected. | DNS pinning remains a later connection-lifetime concern. |
| AC-4 | No bounded outbound client exists. | Fake connection/response tests capture path, headers, SSL context, timeouts, redirect, content type, and body limits. | Server-side transport cannot become a generic fetch/proxy path. | Hosted CI cannot prove real public-CA reachability without an external dependency. |
| AC-5 | Health/capability responses are not consumed. | Canonical Hermes response fixtures plus malformed/unknown/auth-disabled/secret-shaped variants. | Trusted state is authenticated, schema-bound, and minimized. | Complete profile inventory remains an upstream blocker. |
| AC-6 | No routes expose connection state. | Direct route-handler and HTTP boundary contract tests with distinctive credential markers. | Browser receives safe metadata only. | No Settings rendering in this slice. |
| AC-7 | Local behavior has no selection abstraction. | Missing-record default, local confirm, remote-to-local switch, binding rotation, and no-client-call tests. | Existing local mode remains default and endpoint state can be invalidated. | Adapter routing follows in 2B. |
| AC-8 | No slice evidence exists. | Focused/full/static/hosted checks and two adversarial agents. | Regression and independent review gates. | Live approved remote-host compatibility is later Milestone 2 exit evidence. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.13 | Pass | Milestone 1F final local gate: 576 tests, four native-platform skips. |
| Hosted run `29706638264` | GitHub Actions | Pass | Milestone 1F exact head: all 42 supported jobs passed. |
| `rg` over remote connection implementation | Repository | Gap confirmed | Contract exists; no storage, client, discovery, or route implementation exists. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts the mapped
  foundation tests and explicit exclusions without weakening roadmap criteria.
- Accepted coverage gaps: no live external endpoint dependency in ordinary CI;
  upstream-blocked profile/Kanban/clarification capabilities remain explicit.
- Approved at: `2026-07-19` through standing authorization.

## Implementation record

### Changes

- Added `remote_hermes.py` with a strict version-1 private record, missing-record
  local default, bounded nonce-backed single-use HMAC confirmation,
  verification-before-commit, shared private-state locking, binding rotation,
  post-write read-back, and rollback/partial-failure classification.
- Added native Windows protected-DACL creation and read-back for the credential
  directory/file; POSIX requires current ownership and exact `0700`/`0600`
  modes. Links, reparse points, multiple-link files, broad permissions,
  malformed/oversized records, and newer schemas fail closed.
- Added origin-only URL validation and a standard-library direct HTTP client.
  Non-loopback cleartext, arbitrary paths, URL credentials/query/fragment,
  redirects, ambient proxies, invalid certificates, malformed/non-finite JSON,
  unsupported schema, excessive shapes, bodies above 256 KiB, and timeouts are
  rejected with bounded error codes.
- Added fixed public `/health`, authenticated `/health/detailed`, and
  authenticated `/v1/capabilities` discovery. Only allowlisted readiness
  statuses, version/model metadata, and known true capability names survive.
- Added loopback-only server routes for safe summary, preview, exact selection,
  and current-connection testing. Console and other Hermes paths remain local.
- Added 27 focused tests, including real version-2 backup inspection proving
  the connection filename, endpoint, and distinctive credential are absent.
- Preserved the user's concise first-user README rewrite, added one short remote
  status note, and updated old documentation contracts to protect the new quick
  setup promises instead of restoring the removed technical wall of text.

### Deviations and decisions

- Active-profile inventory is not inferred from model metadata; it remains an
  explicit upstream blocker and later Milestone 2 requirement.
- An unchanged selection is re-probed but not rewritten. A probe failure leaves
  the old record exact; an uncertain commit attempts exact rollback and reports
  `partial` only if rollback cannot be verified.
- Endpoint-derived digests are not returned because the endpoint is private and
  often low entropy. The random stored binding is the browser-safe invalidation
  handle.
- Preview grants use a process-private HMAC key, random nonce, five-minute
  expiry, bounded registry, and one-attempt consumption, so a returned token
  cannot verify an API credential offline or authorize a second confirmation.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest -q tests.test_remote_hermes` | macOS, Python 3.13 | `0` | 27 pass | Storage, transport, schema, route, race, rollback, reflection, and real-backup coverage. |
| `python3 -m unittest -q tests.test_remote_hermes tests.test_beta_contract tests.test_data_layout_contract tests.test_request_boundary tests.test_next_phase_readiness` | macOS, Python 3.13 | `0` | 67 pass | Focused feature, docs, data-layout, request-boundary, and README coverage. |
| `python3 -m compileall -q .`; `node --check` for `public/core.js`, `public/app.js`, and `scripts/browser_smoke.mjs`; `git diff --check` | macOS | `0` | All pass | Static and whitespace gates. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | `0` | 603 pass, 4 skip | Final post-review repository suite passed in 76.105 seconds. |

### Rendered or manual behavior

- Not applicable; no visible UI is in scope.

## Adversarial review

### Round 1 findings and corrections

- Safety/privacy review found direct bearer-key reflection through authenticated
  version/model/readiness metadata and a private-directory swap that could
  redirect an unpinned secret write. The client now rejects private reflection;
  every connection operation uses a pinned no-follow parent or Windows
  no-delete guard; rollback removes a raced write through that same handle.
- Safety review also found aggregate-health inconsistencies, permissive record
  variants, wrong-type crashes, empty query/fragment delimiters, and a
  missing-record load race. Strict validation and focused regressions now cover
  each path.
- Compatibility/product review found stale test results across binding changes,
  reusable deterministic confirmations, stale roadmap claims, short-host
  reflection false positives, and incomplete aggregate-health validation.
  Confirmations are now bounded nonce-backed single-use grants, post-probe
  selection is revalidated, short hosts use exact reflection matching, and the
  roadmap/evidence accurately separate 2A from later remote routing.

### Re-review

- Compatibility/product reviewer: **ZERO FINDINGS** on the corrected current
  tree; 27 focused tests and `git diff --check` independently confirmed.
- Safety/privacy reviewer: **ZERO FINDINGS** after all material fixes and the
  corrected 27-test focused evidence were rechecked.

## Documentation updates

- Roadmap: Milestone 2 is in progress with the 2A foundation complete; 2B is the
  next action without marking remote parity complete.
- Changelog: records storage, discovery, routes, exclusions, and local-runtime
  limitation.
- Architecture/operator docs: `ARCHITECTURE.md`, `DATA_LAYOUT.md`, and
  `REMOTE_HERMES.md` describe the implemented boundary and remaining blockers.
- Project/session notes: this review log.
- Documentation verification: focused beta/data-layout contracts pass.

## Publication gate

- Proposed files: `remote_hermes.py`, `server.py`, focused tests and contract
  tests, this review log, beta/remote/data/architecture/changelog docs, and the
  user's beginner-first `README.md` plus durable `AGENTS.md` guidance.
- Branch and base: `codex/beta-2a-remote-hermes-foundation` to `main`.
- Commit message: `Add remote Hermes connection foundation`.
- PR title: `Add remote Hermes connection foundation`.
- PR summary: owner-only selection, bounded authenticated discovery, safe API
  routes, tests, and documentation.
- Unresolved risks: upstream profile, clarification, and Kanban blockers remain.
- User authorization and scope: standing approval recorded.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Pending.
- User decision: standing authorization requires completion and continuation.
- Next slice authorized: Yes, after merge.
