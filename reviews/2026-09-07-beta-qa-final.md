# Beta QA — integrated acceptance

The owner approved all fourteen findings in seven ordered batches before MDA
work, then explicitly requested review-agent subagents after each section.
Baseline: `8eabe696ed7f06286aa786d018f80aad30210672`. The implementation is isolated
on `codex/beta-qa-07-onboarding`; existing MDA checkouts remain separate.

Tracker: [Beta QA audit](https://github.com/hazeion/agent-os/issues/222).

## Local outcome

| Batch | Implemented outcome | Evidence |
| --- | --- | --- |
| 1 | Canonical Run timelines; truthful Codex terminal status and actionable failure guidance | [Execution and visibility](2026-09-07-beta-qa-01-execution.md) |
| 2 | Explicit failed Task recovery; descendant-first cascade deletion with retained guards | [Recovery and deletion](2026-09-07-beta-qa-02-recovery.md) |
| 3 | Integration loading settles; lists, recurrence, search and selection refresh consistently | [Refresh](2026-09-07-beta-qa-03-refresh.md) |
| 4 | Bounded delegation discovery with useful unavailable states; first Apply after restore works | [Availability](2026-09-07-beta-qa-04-availability.md) |
| 5 | Named editable checklists; Someday/return actions; local-time reminders preserving exact instants | [Planning](2026-09-07-beta-qa-05-planning.md) |
| 6 | Shared theme focus/map controls; usable inspector and Board across viewport sizes | [Layout](2026-09-07-beta-qa-06-layout.md) |
| 7 | Confirmed local Hermes Agent setup; fixed Codex identity and Vercel CLI guidance | [Onboarding](2026-09-07-beta-qa-07-onboarding.md) |

Every nontrivial batch received two independent read-only reviews. Findings
were corrected and re-reviewed; no actionable review findings remain. The final
reviewer explicitly used the owner's review-agent skill and reported to the
main agent without editing or publishing.

## Integrated verification

- Node 24.19.0 and Python 3.13 on Windows; production build passed.
- Web lint, typecheck, and all 351 tests passed.
- Cross-batch Python suites: 236 tests passed with four skips; supplemental
  deletion, delegation/deadline, timeline, and Conversation planning: 41 passed.
- Wheel and sdist built with hash-locked native/quality build dependencies;
  exact artifact inventories and wheel RECORD hashes verified, including both
  new Python modules and the lazy Agent setup asset.
- Browser acceptance used standard setup/start with isolated private data.
  Actual UI mutations, failure/retry, successful Codex answer, failed Task
  recovery, exact cascade cleanup, planner changes, restore/Apply, and responsive
  behavior are recorded in the batch logs.
- Lighthouse completed three desktop and three mobile audits using pinned
  Chrome 152.0.7923.0 and Lighthouse 13.4.1. Desktop performance was 100/100/100;
  mobile was 98/98/98. Accessibility, best practices, and SEO were 100 in all six.
  These measurements meet the existing CI performance median requirement of 95,
  but the stricter default requirement of 100 failed on mobile. No threshold or
  product code was changed to disguise that result; full cross-platform CI has
  not run. The CI threshold was verified at the original baseline as well.
- The unchanged gate failed before auditing because Chrome's Windows executable
  did not complete its `--version` probe. An ignored compatibility copy reads
  that executable's version metadata instead. Each attempt uses a fresh browser
  and explicitly owned profile; the launcher otherwise hit a Windows profile
  deletion error. An independent review confirmed identical measurement,
  threshold, retry, and timeout logic. Report this as a Windows compatibility
  audit, not a successful invocation of the unmodified gate.

## Qualification and publication limits

- The installed Codex CLI 0.143.0 received a provider compatibility rejection.
  An isolated QA-only 0.153.4 executable succeeded with the same existing sign-in
  and configuration. Normal use needs a compatible CLI. Global CLI/configuration
  and credentials were not changed; historical missing evidence was not invented.
- This host has no available Hermes CLI. Positive Agent creation and delegation
  capability tests use controlled fixtures, not a real Hermes installation.
  Actual Hermes execution, external calendar linking, browser notification
  delivery, and all runtime/provider combinations are not qualified here.
- This is local Windows verification, not full cross-platform CI or a claim
  that every repository test ran. No source was pushed, no PR was published,
  and GitHub issues remain open pending publication and tracker reconciliation.
- All audit Chrome processes exited. Automatic approval review rejected removal
  of the failed launcher's temporary profile and the six owned profiles under
  ignored `artifacts/qa-lighthouse-profile-*`, reporting only "blocked by policy".
  The directories remain; cleanup was not verified or claimed complete. The
  isolated QA application preview remains available for owner review.
- MDA implementation remains paused. After accepting/publishing this stack,
  reconcile/verify MDA-4A, then rebase/verify MDA-4B and MDA-4C against it.
