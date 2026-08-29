# Feature Slice Review: Agent Console composer Agent configuration

Status: Complete
Slice: `agent-console-composer-agent-configuration`
Date: `2026-08-29`
Review log: `reviews/2026-08-29-agent-console-composer-agent-configuration.md`

## Slice contract

### Goal

Expose the effective Agent, provider, model, and effort in the Home composer
without weakening Mentat's canonical Agent, Hermes profile, active-Run, or
private runtime boundaries. A supported Hermes provider/model change uses the
existing exact preview-confirm-verification workflow and affects only a later
Run. Unsupported adapters stay visible and honestly read-only.

### In scope

- Add one fixed Agent-configuration read capability keyed by canonical Mentat
  Agent ID. Python resolves any private runtime binding.
- Return only explicitly authenticated, profile-scoped Hermes provider/model
  inventory. Keep Codex, Vercel, and unsupported adapters read-only.
- Wrap the existing Hermes provider/model preview and confirmation workflow
  without returning the Hermes profile ID, runtime reference, credential source,
  path, session/thread ID, executable, working directory, or raw provider data.
- Show compact Agent, Provider, Model, and Effort selectors in the composer.
  Unsupported and active states keep their values visible with concise copy.
- Show the selected active Run's immutable safe provider/model/effort snapshot
  when runtime-verified evidence exists. A configuration change is labeled for
  the next Run and cannot rewrite an active Run.
- Preserve exact per-Agent and per-Conversation identity through delayed reads,
  previews, confirmations, tab changes, and concurrent Conversations.

### Out of scope

- Browser-selected Codex executable, model, provider, effort, working directory,
  App Server method, thread, turn, or credential source.
- New credential setup, provider authentication, generic provider catalogs,
  arbitrary runtime methods, or direct Hermes file writes.
- A new effort-mutation capability where the runtime exposes no safe fixed
  workflow. Effort remains a visible read-only runtime default in that case.
- Transcript polish, reasoning summaries, rich links, attachments, artifacts,
  commands, project context, or planning context from later slices.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The composer presents compact Agent, Provider, Model, and Effort controls with loading, unavailable, read-only, active, pending, and confirmed states. | Home interaction, accessibility, mobile browser tests. | Pass |
| AC-2 | Hermes inventory contains only authenticated profile-scoped provider/model choices and the browser never receives the private profile binding. | Server/bridge/BFF hostile projection tests. | Pass |
| AC-3 | Provider/model mutation uses exact preview and confirmation, active-Run exclusion, post-write verification, and existing rollback/partial-failure behavior. | Existing provider suite plus canonical-Agent wrapper tests. | Pass |
| AC-4 | Active Run configuration is an immutable safe snapshot; a confirmed change is clearly for the next Run. | Repository projection and Home active-Run tests. | Pass |
| AC-5 | Codex, Vercel, shared/unsupported bindings, and unsupported effort mutation remain visible but read-only and accept no browser-forbidden values. | Runtime matrix and strict request tests. | Pass |
| AC-6 | Delayed configuration reads and confirmations cannot cross-bind Agents, Conversations, tabs, or Runs. | Race and cross-target canary tests. | Pass |
| AC-7 | Focused/full suites, production build, two independent reviews, and desktop/mobile browser use pass. | Recorded verification and review evidence. | Pass |

### Constraints and recovery

- Python and canonical SQLite Agent/Run authority remain authoritative. Hermes
  provider mutation stays behind the existing fixed supported runtime helper.
- A provider/model confirmation binds the exact live inventory and private
  profile state; changed state requires a new preview.
- No private runtime reference crosses Python. Public request paths use only the
  canonical Agent ID and authenticated provider/model identifiers.
- Lossless rollback remains the existing Hermes provider-switch rollback path.
  Ambiguous or unverified outcomes fail closed and never retry automatically.
- Branch: `codex/agent-console-slice-5`; ready PR into `main`.

### Scope discussion and approval

- The user granted standing approval for every remaining Wayfinder slice,
  scope, commit, push, PR, and merge. That replaces repeated approval pauses.
  Tests, browser use, two independent reviews, CI, and honest outcome records
  remain mandatory.
- Approved at: 2026-08-28 conversation; Slice 5 unblocked by merged Slice 4 on
  2026-08-29.

## Test strategy

| Acceptance criterion | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- |
| AC-1 | Home selector state matrix, keyboard labels, narrow viewport measurement. | The compact controls stay understandable and usable. | Live Hermes inventory may vary; deterministic fixtures cover UI states. |
| AC-2, AC-5 | Strict server/bridge/public parsers with injected paths, runtime refs, credentials, extra providers, and unsupported runtimes. | Only safe authenticated choices cross the boundary. | Provider/model identifiers themselves are intentionally public choices. |
| AC-3 | Canonical-Agent-to-private-profile wrapper tests, stale preview, active Run, verification, rollback, and partial failure tests. | The new surface reuses rather than weakens the existing mutation boundary. | Runtime-specific behavior remains owned by the existing adapter tests. |
| AC-4 | Conversation Run safe snapshot projection before and after a confirmed next-Run change. | Active evidence cannot be rewritten by current Agent state. | A pre-acceptance Run may have no runtime-reported identity yet. |
| AC-6 | Delayed two-Agent/two-tab read and confirmation races. | Late responses cannot alter or label the wrong target. | No cross-Conversation scheduler is introduced. |
| AC-7 | Focused Python/web gates, full suite, production build, browser exercise, two adversarial reviewers. | Slice works as an integrated milestone. | Standard Turbopack may remain CI-only if local sandbox worker ports are unavailable. |

### Test discussion and approval

- Standing approval covers this strategy. No production adapter gains an effort
  mutation or Codex browser model selector without a separate safe runtime
  capability.

## Implementation record

- Added canonical-Agent configuration read, preview, and confirmation
  capabilities. Python resolves the private runtime binding and returns only a
  safe configuration projection keyed by Mentat Agent ID.
- Reused the existing Hermes authenticated inventory and provider switch
  implementation, including active-Run exclusion, exact state-bound preview,
  post-write verification, rollback, and partial-failure classifications.
- Kept Codex, Vercel, unsupported runtimes, and effort mutation read-only. The
  browser receives labels and runtime-default effort, not a private choice.
- Added compact composer controls, pending confirmation, next-Run copy, delayed
  Agent/tab response guards, and an immutable active Run configuration snapshot
  derived from the durable runtime execution identity.
- Added strict bridge, BFF, and browser parsers plus bounded response reads and
  exact same-origin request bodies.

## Verification

- Focused backend configuration, provider, Conversation, orchestration, legacy
  Console, and profile-aware suites: 165 passed.
- Host loopback local bridge suite: 42 passed.
- Web lint, typecheck, and 114 tests: passed.
- Next.js webpack production build and standalone preparation: passed; both new
  fixed configuration routes compiled.
- Production browser: Direct Codex configuration rendered read-only; a real
  Retry showed `openai · gpt-5.6-sol · Medium` from the active immutable Run
  snapshot; controls stayed disabled and the exact Run was stopped after
  verification. At `390x844`, the document width remained 390 and all four
  selectors measured 44 px high without overflow.
- Full host suite: 1,651 passed, 5 platform skips in 577.124 seconds.
- Final post-review production recheck retained the same read-only Codex values,
  390 px document width at a 390 px viewport, and four 44 px-high selectors.

## Adversarial review

### Round 1

- Safety reviewer blocked on a confirm deadline shorter than the existing
  bounded provider-switch workflow and an unresolved-Conversation identity
  window. Corrections: bridge read/preview/confirm budgets are 40/70/190 seconds
  with browser budgets 45/75/195 seconds; confirm transport uncertainty maps to
  partial. Configuration stays null and Agent locked until exact Conversation
  detail resolves. Safety re-review is clean.
- Product reviewer blocked providers lacking explicit `authenticated: true`,
  remote Hermes mutation, same-Agent tab handoff staleness, dishonest read-error
  copy, and focus loss. Corrections: authentication is strict; remote Hermes is
  read-only and mutation rejects before the legacy operation; configuration
  state is scoped and refetched by Agent plus Conversation; unavailable,
  unsupported, and unsafe reads are distinct; preview focuses Confirm and
  completion/error returns focus to Provider. Hostile authentication, remote,
  same-Agent delayed preview/confirm, unresolved detail, state-copy, and focus
  tests cover the fixes.

### Round 2

- Safety reviewer initially found the inverse same-Agent ordering: the selected
  tab's old GET could win before confirmation, leaving it stale. Every verified
  confirmation now increments a refresh generation before origin discard, and
  the inverse-order test proves the selected tab performs a post-confirm GET.
- Product reviewer found remote alternate inventory still visible and a pending
  Confirm surviving active Run start. Remote mode now exposes only current
  identity with no alternate provider/model rows; active Run admission clears
  preview and Confirm also disables immediately.

### Round 3

- Safety reviewer: clean, no findings.
- Product/accessibility/compatibility reviewer: clean, no findings.

## Documentation updates

- Updated `AGENTS.md` and `ARCHITECTURE.md` with canonical-Agent targeting,
  local-only Hermes mutation, remote identity minimization, next-Run behavior,
  and immutable active snapshot rules.
- Updated `CHANGELOG.md` and this review record.

## Publication gate

- All 52 fresh PR checks passed. PR #150 merged as
  `ca4ae2d88d73371ef44ba57d69127ff7503c90f9`; issue #137 closed and Wayfinder
  #128 records the resolution and advances to Slice 6.

## Outcome review

- Classification: Successful and merged.
