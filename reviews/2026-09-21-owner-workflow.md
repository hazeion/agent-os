# Secure owner access and coordinated Project delivery

## Approved scope

The owner approved the product decisions and requested implementation through
issue completion on September 21, 2026. The canonical scope and dependencies
live in the [owner workflow map](https://github.com/hazeion/agent-os/issues/234).
This log records reconciliation and review evidence, not a second roadmap.

Baseline: `038f1d1`, clean tracked checkout. Work branch:
`codex/mentat-owner-workflow`.

## Initial reconciliation

- PR 231 merged the original fourteen Beta QA fixes and additional fresh-install
  changes. PRs 207, 232 and 233 completed MDA-4A through MDA-4C. Historical logs
  that describe these as unpublished are historical evidence, not current status.
- Independent read-only audit found original issues 208-221 have per-batch
  implementation, review and browser/fixture evidence. Live Hermes and external
  integrations remain unqualified; closure must retain those limitations.
- Issues 224 and 225 were already closed. Issue 229 has merged source/setup
  guidance; full fresh-install replay remains an acceptance-map responsibility.
- Issue 226 remains incomplete: readable bounded results and revision-bound
  requested changes shipped, but the next-Run preview does not expose the
  effective objective and review feedback.
- Issue 227 remains incomplete: manual execution refresh shipped, but automatic
  completion refresh, Run-card reconciliation and working Task navigation still
  need implementation and verification.
- Issue 228 needs focused 320px scrollbar and retained-scroll browser acceptance.
- Issue 230 retains the unresolved Stop/cancel transcript refresh observation;
  seed cleanup alone is not complete resolution.

## First implementation slice and validation

Complete the bounded next-Run preview in issue 226 before changing Task live
refresh. Derive the preview from the exact server-owned objective/review state
bound by confirmation; never accept browser-supplied execution text. Preserve
redaction and bounded projections. Verify initial and requested-change previews,
stale revision/confirmation refusal, exact public schema validation, and rendered
confirmation content. Run focused Python and web tests, then relevant type/lint
checks. Obtain two independent read-only reviews before closing the slice.

Authentication and runtime qualification are independent research children.
No OAuth credentials, public listeners, or provider execution are created by
this planning/reconciliation work.

## Status

The map and eight native child issues are published with blocking dependencies.
Original QA issues 208-221 and their historical audit umbrella are closed with
merged evidence and explicit qualification limits; fresh-install acceptance
remains open. Existing MDA and fresh-install maps now point to the current work.

Issue 226 implementation adds a bounded readable objective to Run once, using
the exact shared runtime objective builder and revision-bound review receipt.
Confirmation includes the raw objective digest; redaction never changes what
the runtime receives. All server/bridge/browser schemas and the UI agree.

Initial verification: 23 Python recovery/planning tests and 99 web planning
contract/UI tests passed. TypeScript and ESLint passed using their installed
Node entrypoints because the global npm shim points to a missing npm-cli.js.
System Python 3.13 lacks Pillow; the existing supported Python 3.11.5 project
venv runs the tests. This is environment evidence, not an application failure.

Two independent read-only reviews completed. One found the Python bridge's old
exact-key schema rejected the new preview. Fixed its validator/projection and
added a real server-to-bridge regression, including hostile objective rejection.
Both reviewers rechecked the complete path and report no remaining actionable
findings. The broader recovery/bridge/orchestration suite passed 175 tests.
The optimized Next.js production build also passed. These checks establish the
preview slice; they do not close the broader live-state or garage acceptance.
