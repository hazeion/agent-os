# Feature Slice Review: Emerald foundation and application shell

Status: Outcome accepted and publication authorized — publishing
Slice: `emerald-foundation-shell`
Date: `2026-07-25`
Review log: `reviews/2026-07-25-emerald-foundation-shell.md`

## Slice contract

### Goal

Give Mentat its new Emerald visual foundation, responsive application shell,
and reference-aligned operations Home without changing the behavior or
information architecture of the six existing views. The product remains named
**Mentat**. Operator identity remains available to assistive technology and in
the top-bar avatar, but the visible greeting hero is removed from Home.

### In scope

- Keep the visible product name `Mentat`; do not introduce `Mentat Operations`.
- Preserve the dynamic greeting built from the configured greeting prefix and
  display name as an accessible page heading and operator-avatar label.
- Add the Emerald primitive and semantic color/token foundation.
- Add Emerald as a saved, no-flash site theme and preserve existing explicit
  theme choices.
- Add Standard, High Contrast, and system-derived contrast handling.
- Add a saved `emerald` / `classic` shell selection with Emerald as the default
  when no explicit shell choice exists.
- Convert the effective desktop shell to an expanded left navigation rail.
- Provide a compact intermediate-width rail and an accessible narrow-screen
  navigation drawer.
- Keep the six current internal view keys and their existing view panels.
- Keep global search, health, refresh cadence, and last-updated state reachable.
- Add a skip link, current-page semantics, accessible icon controls, keyboard
  drawer behavior, Escape handling, and focus return.
- Use a transparent, color-corrected derivative of the existing Mentat portrait
  in the new shell while retaining the existing source logo.
- Update static-asset packaging contracts for any new production asset.
- Add and update focused UI, theme, shell, accessibility, packaging, and
  browser tests for the changed behavior.
- Replace the legacy Home composition with the approved reference hierarchy:
  Operational Focus and Live Agents on the first row, Today schedule and
  project/automation context beneath, and Agent Console as the bottom command
  strip.
- Remove the five-card overview/metric row from Home.
- Render Live Agents from real Hermes profile, Console run, task, and
  project-owned heartbeat data; do not invent example agents.
- Keep quick capture, reminders, completed work, agent review work, full
  Console history, attachments, provider review, and run controls reachable
  through compact disclosures instead of restoring the legacy panel stack.
- Add a compact, read-only Scheduled Automations inventory to Home while
  preserving the existing fail-closed Hermes CRON boundary.

### Out of scope

- Correcting the separate local/remote CRON payload issue.
- Removing the existing read-only CRON monitor or queue-failure server
  boundary.
- Reorganizing Agents & Sessions, Projects & Tasks, Calendar, Notes & Context,
  Settings, or dialogs.
- Splitting current combined routes into new internal views.
- Changing task, agent, provider, calendar, note, attachment, or delegation
  behavior.
- Implementing local/remote Hermes switching.
- Removing legacy color themes.
- Deleting the existing Compact Dark CSS before the full redesign reaches
  parity.
- Staging, committing, pushing, or opening a pull request without a separate
  publication approval.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The production shell visibly brands the product as `Mentat`, never `Mentat Operations`; configured operator identity remains available in the avatar and accessible page heading without restoring a visible greeting hero. | DOM contract tests and rendered screenshots with configured identity data. | Passed |
| AC-2 | Emerald tokens, theme registration, theme preloading, shell preloading, and Standard/High Contrast behavior apply before CSS without discarding an existing explicit theme or shell choice. | Theme/shell unit-contract tests and reload checks. | Passed |
| AC-3 | The shell renders an expanded left rail on desktop, a compact rail at intermediate widths, and a keyboard-operable drawer below 900 px. | Computed-layout browser checks and screenshots at agreed viewports. | Passed |
| AC-4 | Home, Agents & Sessions, Calendar, Projects & Tasks, Notes & Context, and Settings continue to use the existing `today`, `agents`, `calendar`, `projects`, `notes`, and `settings` keys and remain reachable. | Source contract tests and browser navigation smoke. | Passed |
| AC-5 | Global search, subsystem health, refresh cadence, last-updated state, and every currently required shell mount remain present exactly once and functional. | DOM uniqueness/mount tests and browser interaction. | Passed |
| AC-6 | Active navigation exposes `aria-current`, the skip link works, icon controls retain accessible names, drawer focus is managed, Escape closes it, and focus returns to the opener. | Focused accessibility contract tests and keyboard browser checks. | Passed |
| AC-7 | The shell uses a transparent color-corrected derivative of the current Mentat portrait, the source logo remains available, and packaged builds include every referenced production asset. | Asset inspection and packaging tests. | Passed |
| AC-8 | Existing page renderers, dialogs, API calls, Agent Console polling, and mutation safeguards are unchanged by the shell slice. | Focused workflow suites, full suite, and diff inspection. | Passed |
| AC-9 | No page-level horizontal overflow occurs at 1680, 1440, 1024, 768, or 390 px; the greeting and primary navigation remain visible and usable at each width. | Browser bounding-box checks and reviewed screenshots for all six pages. | Passed |
| AC-10 | A saved Classic shell remains a working rollback during the incremental redesign, while an unsaved installation opens with the Emerald shell. | Storage/reload browser checks and source contract tests. | Passed |
| AC-11 | Home has no overview metric-card row and follows the reference hierarchy: Operational Focus and Live Agents first, Today schedule and project/automation context second, and Agent Console last. | DOM ordering contract plus rendered desktop/tablet/mobile screenshots. | Passed |
| AC-12 | Live Agents is visible on Home and uses actual profile, run, task, and heartbeat data with honest ready/working/attention/unavailable states. | Renderer tests and live browser data checks. | Passed |
| AC-13 | Operational Focus presents a bounded priority list and completion summary; Today presents an actual time-oriented schedule; Projects presents portfolio state; Scheduled Automations presents real read-only CRON inventory. | Source contracts, computed browser layout, and live data rendering. | Passed |
| AC-14 | Quick capture, reminders, completed work, agent review work, Console history, attachments, provider review, new-session, stop, and send workflows remain reachable and operable after compaction. | Existing focused workflow suites plus browser disclosure and Console-control checks. | Passed |
| AC-15 | The corrected Home composition has no horizontal overflow or obscured content at 1680, 1440, 1200, 1024, 900, 768, and 390 px, with two columns where usable and deterministic stacking on narrower screens. | Bounding-box, target-size, and ordering assertions across the responsive browser matrix. | Passed |

### Constraints and recovery

- Safety: no Hermes API, storage, credential, or mutation boundary changes.
- Compatibility: preserve all six view keys, required mount IDs, search
  combobox relationships, current Agent Console view behavior, and existing
  saved theme values.
- Rendered behavior: proportional sentence-case typography, warm ivory content,
  restrained emerald state cues, desktop rail, compact rail, mobile drawer,
  and an operations-first Home with no greeting or metric-card layer above it.
- Rollback or recovery: `data-ui-shell="classic"` remains selectable and
  persisted during the redesign. Reverting the slice removes the new shell
  without data migration.
- Documentation targets: this review log and any theme/shell contributor
  contract affected by implementation.
- Version-control strategy: implement in isolated worktree
  `/private/tmp/mentat-emerald-foundation-shell` on
  `codex/emerald-foundation-shell`, based on `origin/main`. Do not stage,
  commit, push, or open a PR before the publication gate.

### Scope discussion and approval

- Recommendation and rationale: establish the shared visual foundation and
  responsive shell first so later page conversions compose into one stable
  frame without changing functional page contracts at the same time.
- Alternatives considered:
  - A token-only slice would reduce initial rendered change but would leave the
    most visible shell transition for a separate pass.
  - A combined shell-and-Home conversion would provide more immediate page
    similarity but would mix navigation, CRON, task planning, and Console risks.
  - Implementing on the existing beta-policy branch would mix unrelated
    histories and dirty documentation changes.
- User decisions: keep the product name `Mentat`; keep the personalized greeting
  at the top; approve the foundation/shell boundary, review-log path, and
  isolated branch strategy.
- Approved at: user approval in this Codex task on `2026-07-25`.

## Test strategy

Status: approved.

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Current UI says Mentat but still appends `Mission Control`; design references used a working `Mentat Operations` label. | Source contract for visible brand/title, avatar identity, and visually hidden greeting heading plus browser identity rendering. | Product branding and operator identity remain correct without a visible Home hero. | Does not judge subjective typography quality. |
| AC-2 | Emerald, shell storage, and contrast storage do not exist. | Preloader/registry/selector/token tests; reload checks with empty and populated storage. | No-flash initialization and preference preservation. | Static checks alone cannot prove first-paint timing, so browser reload evidence is also required. |
| AC-3 | Effective Compact Dark CSS creates a horizontal top bar with no drawer. | CSS contract plus browser bounding-box assertions at 1680, 1024, 768, and 390 px. | Correct shell mode and responsive transitions. | Cross-platform font rasterization is not pixel-diffed. |
| AC-4 | Existing view keys work in the old shell only. | Preserve-key source assertions and click every navigation item in browser smoke. | Navigation behavior survives the DOM/style change. | Does not exhaust page-specific workflows, which remain covered by existing suites. |
| AC-5 | Required mounts exist today but there is no uniqueness regression check. | Required-ID uniqueness test and live search/status interaction. | Shell moves do not remove or duplicate critical mounts. | Dynamic dialog mount behavior remains covered by existing tests. |
| AC-6 | Active nav uses a class but not `aria-current`; no narrow-screen drawer exists. | Focused DOM/accessibility tests and keyboard-only browser pass. | Semantics, focus entry/exit, Escape, and return behavior. | Full assistive-technology testing remains manual. |
| AC-7 | The transparent design asset is not web-served or packaged. | PNG alpha/dimension inspection, referenced-file tests, wheel/sdist artifact verification. | Production and packaged builds contain the referenced logo. | Visual faithfulness still needs screenshot review. |
| AC-8 | Shell changes could affect global event handlers or polling. | Existing focused UI/workflow suites, JavaScript syntax checks, full unit suite, and diff audit. | No intended behavior/API change and broad regression coverage. | Hosted platform packaging and browser differences remain CI evidence. |
| AC-9 | Current shell wraps horizontally and has no agreed overflow matrix. | Browser `scrollWidth`/bounding-box checks and screenshots on all six pages at five viewports. | Responsive usability and overflow constraints. | Screenshots are reviewed evidence, not brittle CI pixel diffs. |
| AC-10 | No independent shell rollback exists. | Empty/saved storage reload matrix and Classic/Emerald smoke. | Default and rollback behavior are both functional. | Rollback is visual only; no data migration is involved. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_visual_contract tests.test_daily_workflow_ui tests.test_frontend_workflow_feedback -v` | Existing macOS development checkout | Pass, 34 tests | Current visual, daily workflow, search, CRON failure, and feedback contracts pass before implementation. |
| Live Home screenshot at `http://localhost:8888/` | Existing running Mentat instance | Captured | Confirms current horizontal Compact Dark shell and personalized greeting baseline. |
| `node --check public/core.js && node --check public/app.js && node --check scripts/browser_smoke.mjs` | Clean isolated worktree at `origin/main` | Pass | Establishes a clean JavaScript syntax baseline for the application and browser-smoke entry points. |
| Focused UI/workflow command covering 13 test modules | Clean isolated worktree at `origin/main` | Pass, 129 tests | Covers the existing visual, daily workflow, calendar, usability, feedback, agent, attachment, context-pack, remote inventory, delegation, dashboard, CRON, and packaging contracts. |
| `python3 -m unittest discover -s tests -v` | Clean isolated worktree at `origin/main` | Pass, 768 tests; 4 skipped | Establishes the full-suite regression baseline before implementation. |

### Test discussion and approval

- User questions and decisions: The user approved the proposed strategy and
  asked Codex to proceed without repeating routine implementation approvals.
- Accepted coverage gaps: No complete screen-reader pass or hosted OS package
  installation is available locally. The slice will use semantic contract
  checks, keyboard browser checks, artifact verification, and the existing CI
  packaging boundary.
- Approved at: user approval in this Codex task on `2026-07-25`.

## Outcome feedback and revised scope

- Initial outcome decision: rejected on `2026-07-25`.
- User feedback: the first implementation adopted the Emerald styling but
  retained Mentat's previous Home layout. The required outcome is also the
  reference composition, specifically Live Agents on Home and no hero/metric
  cards above the workspace.
- Root cause: the first slice contract explicitly deferred Home reorganization,
  which preserved the wrong information hierarchy even though the visual
  language matched.
- Revised decision: reopen this slice rather than treating the layout as an
  unrelated future enhancement. Preserve the accepted visual foundation and
  expand the Home boundary through AC-11–AC-15.
- Authorization: the user's correction and standing approval authorize this
  bounded Home-layout implementation and its agreed verification. Publication
  remains a separate gate.

### Revised test strategy

| Acceptance criterion | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- |
| AC-11 | Static DOM/order assertions and browser panel-position checks. | The reference hierarchy replaces, rather than merely restyles, the old Home stack. | Does not pixel-diff against the concept image. |
| AC-12 | Renderer contracts plus browser payload injection for working, ready, attention, unavailable, and empty inventories. | Home agent status is real and degrades honestly. | Live heartbeat timing remains environment-dependent. |
| AC-13 | Focus/schedule/project/CRON renderer tests and computed panel checks. | Every major reference panel is driven by existing Mentat data. | Calendar event geometry is representative rather than exhaustive. |
| AC-14 | Existing Console, calendar, task, review, attachment, and CRON suites plus disclosure interaction smoke. | Visual compaction does not silently remove workflows. | Complete assistive-technology validation remains manual. |
| AC-15 | Seven-width browser matrix covering panel order, overflow, target size, and narrow stacking. | The richer Home remains usable across the supported shell breakpoints. | Safari/Firefox remain a manual follow-up. |

## Implementation record

### Changes

- Added an Emerald-first primitive and semantic token system, a registered
  Emerald color theme, and an independently persisted Emerald/Classic shell
  preference.
- Added a pre-CSS preference initializer for the saved color theme, shell, and
  system/standard/high contrast preference so the initial render uses the
  resolved appearance.
- Reframed the unchanged six-view application in a responsive left-navigation
  shell: 216 px desktop rail, 76 px compact rail, and a drawer at 900 px and
  below.
- Added sentence-case navigation labels and line icons while preserving the
  exact existing internal view keys and content mounts.
- Explicitly restored single-column row flow for compact navigation groups so
  legacy grid rules cannot arrange the six destinations horizontally.
- Added the mobile drawer overlay and close control, focus containment, Escape
  handling, opener focus return, skip navigation, `aria-current`, and visible
  focus treatment.
- Made the mobile workspace header sticky, moved the drawer opener into that
  header, and made the compact and drawer media ranges non-overlapping.
- Added a keyboard- and hover-reachable compact status disclosure so health,
  workflow feedback, refresh cadence, and last-updated state remain available
  in the 76 px rail.
- Kept the dynamic configured greeting as the workspace heading and removed the
  legacy `Mission Control` suffix from the document title. Product branding and
  the title are pinned to `Mentat`.
- Added Settings controls for color theme, shell, and contrast preference
  without removing any existing color themes.
- Applied resolved High Contrast tokens across every color-theme/shell
  combination and added a dedicated control-boundary token meeting the 3:1
  non-text contrast threshold in the default Emerald palette.
- Created `public/mentat-mark-emerald.png`, a transparent color-corrected
  derivative of the existing portrait, while retaining
  `public/mentat-logo.png`.
- Added the new image to source, wheel, sdist, and PyInstaller asset
  inventories and expanded the artifact verifier and packaging tests.
- Expanded static visual-contract and browser-smoke coverage for preferences,
  accessibility, responsive layout, all six views, rollback, and mobile
  keyboard behavior.
- Removed the Home overview-card mount and client renderer while preserving the
  backend overview payload for compatibility.
- Rebuilt Home as a two-column operations surface: bounded Operational Focus
  beside Live Agents, day schedule beside Projects and Scheduled Automations,
  and a full-width compact Agent Console dock.
- Merged canonical Console profiles with active Console runs, delegated Mentat
  tasks, and matching project-owned heartbeat observations for the Home agent
  rows. Unmatched observations do not become managed identities.
- Added real completion math and deterministic Today ordering to Operational
  Focus, a one-day read-only time grid with a phone agenda fallback, portfolio
  and queue summaries, and a two-item read-only CRON inventory.
- Preserved quick capture, completed work, agent review, Console history,
  provider review, attachment, stop, and new-session controls in native
  disclosures. Collapsed disclosure descendants are explicitly removed from
  layout so the Console remains a compact dock.
- Added `tests/test_home_operations_ui.py`, updated stale page contracts, and
  expanded browser smoke to assert Home geometry, absence of metric cards,
  disclosure behavior, mobile reading order, touch-target size, and overflow.

### Deviations and decisions

- An explicitly saved legacy color theme remains authoritative when the user
  selects the Emerald shell. Compatibility token mappings let that theme use
  the new shell safely; a fresh origin still defaults to Emerald.
- Selecting a navigation destination now scrolls the document to the top so a
  newly selected page cannot inherit a misleading deep scroll position from
  the previous page. This is shell navigation behavior only.
- The top-bar greeting is visually hidden on the Emerald shell because the
  corrected reference has no hero. Its text remains the page heading for
  assistive technology and labels the operator avatar.
- Scheduled Automations show at most the next two real jobs in a separate
  compact region beneath Projects. The surface is intentionally read-only and
  exposes no queue, run, edit, enable, disable, or delete control.
- The existing six combined views remain unchanged; matching the reference
  sidebar with separate Today, Tasks, and Sessions routes remains an
  information-architecture decision outside this slice.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `node --check public/core.js`; `node --check public/app.js`; `node --check scripts/browser_smoke.mjs` | Isolated worktree | Exit 0 | 3 pass | JavaScript syntax is valid after implementation. |
| Approved focused UI/workflow suite covering 13 modules | Isolated worktree | Exit 0 | 133 pass, 0 fail, 0 skip | Covers visual, workflow, calendar, agent, attachment, delegation, CRON, feedback, and packaging contracts after reviewer fixes. |
| `python3 -m unittest tests.test_home_operations_ui tests.test_visual_contract tests.test_calendar_week_ui tests.test_agent_console_attachments_ui -q` | Isolated worktree | Exit 0 | 60 pass, 0 fail, 0 skip | Covers the corrected Home hierarchy, real data mappings, waiting-for-input Console states, retained Console mounts, schedule routing, accessibility labels, and responsive CSS contract. |
| `git diff --check` | Isolated worktree | Exit 0 | Pass | No whitespace errors. |
| `CHROME_PATH='/Applications/Chromium.app/Contents/MacOS/Chromium' MENTAT_BASE_URL='http://127.0.0.1:8891' MENTAT_BROWSER_DEBUG_PORT=9332 node scripts/browser_smoke.mjs` | Isolated loopback server and disposable Chromium profile | Exit 0 (`{"ok":true}`) | Pass | Exercises computed contrast, saved shell/theme reload, Classic rollback geometry, corrected Home hierarchy, no metric cards, disclosures, exact transport binding, concurrent schedule lanes, 23:45 end-of-day target geometry, unavailable/working agent ordering, approval/clarification waiting states, rich accessible names, drawer/focus behavior, and all six views at 1680/1440/1200/1024/900/768/390 px. |
| PNG metadata and alpha inspection plus packaging-focused tests | Isolated worktree | Pass | Pass | `mentat-mark-emerald.png` is a 940×940 RGBA image with real transparent pixels and is present in every production asset inventory. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | Isolated worktree | Exit 0 | 783 pass, 0 fail, 4 skipped | Baseline was 768 pass and 4 skipped; the increase covers the shell foundation, corrected Home operations contract, and final adversarial edge cases. |

### Rendered or manual behavior

- Reviewed Home, Agents & Sessions, Calendar, Projects & Tasks, Notes &
  Context, and Settings in the live Emerald shell at desktop width.
- Reviewed the corrected Home at 1280 px against the reference hierarchy:
  first-row Focus/Live Agents, aligned Schedule/Projects-and-CRON context,
  full-width compact Console, no visible hero or metric cards, and no
  horizontal overflow.
- Reviewed a browser origin with an existing explicit light theme: the saved
  color choice remained in effect while the new shell rendered without missing
  semantic colors.
- Confirmed operator identity remains accessible in the hidden heading/avatar,
  subsystem health and refresh metadata remain present, and all six navigation
  destinations render in place.
- Final corrected outcome artifact:
  `/Users/hazeion/.codex/visualizations/2026/07/21/019f8365-1605-7890-b747-6e657840d044/emerald-home-corrected.png`.
  The earlier `emerald-home-1280.png` is retained only as rejected baseline
  evidence and must not be presented as the corrected outcome.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Uncommitted working-tree diff on
  `codex/emerald-foundation-shell` against `origin/main`; 12 modified text
  files, one new production PNG, and this review log.
- Verification evidence: JavaScript syntax checks, 132-test focused suite,
  771-test full suite, packaging/alpha checks, `git diff --check`, and passing
  live browser smoke.
- Rendered artifacts:
  `/private/tmp/mentat-emerald-browser.TugKuY/screenshots/emerald-home-1280.png`
  plus live review of all six views.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | At 390 px the absolutely positioned drawer opener was painted below the sticky header; a physical center-point click hit the header while the smoke used `toggle.click()`. AC-3/6/9. | Yes | Put the opener in or above a persistent mobile header and add a real pointer hit-test. |
| A-2 | Medium | Yes | The legacy below-1120 rule hid drawer item labels, leaving an otherwise wide drawer with unlabeled icons. AC-3/9. | Yes | Restore visible drawer labels and assert computed visibility. |
| A-3 | Medium | Yes | The focus list included the opener outside and behind the modal drawer. AC-6. | Yes | Restrict focus containment to visible sidebar controls and test wrapping. |
| A-4 | Medium | Yes | The compact rail hid health, refresh, and updated text with zero-sized boxes. AC-5. | Yes | Provide a compact disclosure that is visually and keyboard reachable. |
| A-5 | Medium | Yes | Classic plus a legacy color theme did not match either High Contrast selector; smoke checked only the data flag. AC-2/10. | Yes | Apply the resolved contrast root-wide and verify computed styling. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Corroborated the covered opener, then showed it also scrolled out of view and that overlapping media queries hid the 900 px drawer close/text. AC-3/6/9. | Yes | Use a sticky mobile header and non-overlapping compact/drawer ranges. |
| B-2 | High | Yes | Corroborated the external opener in the focus loop and noted rendered visibility was not checked. AC-6. | Yes | Use only rendered sidebar controls, modal semantics, and bidirectional wrap tests. |
| B-3 | High | Yes | Compact hiding also removed the sole feedback surface used by note, calendar, Today-order, checklist, and refresh workflows. AC-5/8. | Yes | Keep the live feedback/status content reachable in compact mode. |
| B-4 | Medium | Yes | Corroborated Classic High Contrast and found legacy aliases could survive even in the Emerald shell. AC-2/10. | Yes | Override both semantic tokens and compatibility aliases at resolved root state. |
| B-5 | Medium | Yes | A configured `identity.app_name` could still replace visible branding/title despite the Mentat-only criterion. AC-1. | Yes | Pin product brand/title to Mentat; personalize only the greeting. |
| B-6 | Medium | Yes | Default control border against input surface measured about 1.55:1, below the 3:1 non-text boundary criterion. AC-2/6. | Yes | Add and use a stronger interactive boundary token. |
| B-7 | Medium | Yes | Browser smoke omitted physical click hit-testing, 900 px, Tab wrap, compact status, and actual skip-link activation. | Yes | Add those browser checks and retain rendered evidence. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Covered, scrolling, and 900 px mobile navigation; hidden labels | A-1/A-2 and B-1/B-7 corroborated | Resolved in re-review | Accept. Physical hit-testing reproduced the defect. | Moved the opener into the sticky command header, separated `901–1199` compact from `≤900` drawer rules, and restored drawer labels/close control. |
| Focus escaped to an occluded opener | A-3 and B-2/B-7 corroborated | Resolved in re-review | Accept. The opener is outside the modal interaction region. | Made the main (including opener) inert while open, restricted focusables to rendered sidebar controls, added dialog/modal semantics, and tested forward/reverse wrap. |
| Compact status and workflow feedback disappeared | A-4 and B-3 corroborated | Resolved in re-review | Accept. This was a compatibility issue, not cosmetic truncation. | Kept live status text accessibility-visible and added an expanding hover/focus disclosure with health, refresh, and updated details. |
| High Contrast did not cross all saved theme/shell combinations | A-5 and B-4 corroborated | Resolved in re-review | Accept. A data attribute without a visual delta was insufficient. | Changed High Contrast to a root-wide resolved override covering Operations tokens and legacy aliases; browser smoke asserts computed Classic styling. |
| Arbitrary configured product branding | B-5 unique | Resolved in re-review | Accept under the approved Mentat-only criterion. Greeting prefix/display name remain dynamic. | Pinned brand and document title to `Mentat`; ignored `identity.app_name` for product branding. |
| Default control boundary below 3:1 | B-6 unique | Resolved in re-review | Accept. Panel separators may remain subtle, but interactive boundaries need their own stronger token. | Added `--operations-border-control` and applied it to searches, form controls, buttons, and mobile controls; live smoke requires a ratio of at least 3:1. |
| Verification could bypass or omit the defects | B-7 corroborated several findings | Resolved in re-review | Accept. Tests now reproduce the user interaction rather than invoking handlers directly. | Added 900 px, real pointer input after scroll, rendered label checks, compact disclosure, modal/focus wrap, computed contrast, and keyboard skip-link activation. |
| Legacy compact-navigation grid cascade | Root discovery, corroborated by Reviewer B | Resolved in re-review | Accept. Live review at 911 px showed groups arranging horizontally despite correct rail width. | Emerald now forces one `minmax(0, 1fr)` column with row flow; browser smoke requires all six compact destinations to stack vertically. |

### Reverification

- Focused tests: JavaScript syntax and `git diff --check` pass; approved
  13-module suite passes 133/133.
- Full suite: 772 pass, 0 fail, 4 platform skips.
- Rendered browser: upgraded smoke passes with `{"ok":true}` across six views
  and six viewport widths, including physical pointer and keyboard checks.
- Reviewer A re-review: A-1 through A-5 and the compact navigation cascade are
  resolved; no blocking findings.
- Reviewer B re-review: B-1 through B-7 and the compact navigation cascade are
  resolved; no blocking findings.
- Next review round or gate result: adversarial review is closed. The only
  accepted residual risk is manual cross-browser and screen-reader validation.

## Home correction adversarial review

The reopened Home outcome was reviewed by two fresh, independent adversarial
reviewers after implementation. They reviewed the same uncommitted worktree
against AC-11 through AC-15 from different perspectives and made no edits.

### Reviewer C — correctness, safety, and compatibility

| ID | Severity | Blocking | Finding and evidence | Resolution |
| --- | --- | --- | --- | --- |
| C-1 | High | Yes | Open Quick Add and Completed Work disclosures inherited legacy width/flex rules and clipped content at intermediate widths. | Made open disclosures consume one bounded flex row and reset descendant width/min-width; added open-state checks at every supported width. |
| C-2 | High | Yes | Home could label a future event date as Today when the current day had no event, and raw calendar error detail could leak into the compact heading. | Pinned Home to the current local day, selected overlapping events only, and mapped disconnected/error states to bounded operator copy. |
| C-3 | High | Yes | Classic rollback retained stale grid-area assignments, causing Home panels to overlap after the DOM reorganization. | Added a complete Classic Home template and explicit area resets; browser smoke now verifies Classic geometry. |
| C-4 | High | Yes | Approval and clarification waits were not active Console states; polling and Stop could disappear while the composer remained enabled. Runs from another connection binding could also color Home status. | Added both wait states to the active-state contract, retained polling/Stop, disabled the composer, and filtered runs by exact transport mode and binding. |
| C-5 | Medium | Yes | The schedule used time-only lane assignment, which failed for arbitrary overlaps and minimum-width late events. The first boundary fix could still overlay a nearby event, and the phone agenda inherited a desktop max-width that reduced late targets below 44 px. | Assigned lanes from final visual intervals, made track height lane-driven, tested adjacent 22:30/23:45 events at seven widths, reset the phone max-width, and require 44×44 px touch targets. |
| C-6 | Medium | Yes | Repeated Home list replacement, terse agent/project labels, and color-only CRON state weakened assistive-technology output. | Removed whole-list live announcements, added progressbar semantics and descriptive accessible names, and rendered explicit Enabled/Disabled CRON text. |

### Reviewer D — product behavior and rendered outcome

| ID | Severity | Blocking | Finding and evidence | Resolution |
| --- | --- | --- | --- | --- |
| D-1 | High | Yes | Corroborated disclosure clipping, Today date drift, and the Classic rollback overlap as visible product regressions. | Same root fixes as C-1 through C-3; the seven-width matrix and Classic reload checks now reproduce the actual rendered states. |
| D-2 | High | Yes | Unavailable profiles could rank ahead of a working profile in the three-row Home limit, hiding the most operationally important agent. | Added a distinct unavailable state and rank after attention, working, and ready; a four-profile fixture requires the working profile to remain visible. |
| D-3 | High | Yes | A 23:45–24:00 event could collapse at the right edge. After widening, it could obscure a prior non-overlapping event because lanes used the original time intervals. | Compute width/shift before lane selection, allocate from final visual left/right edges, and assert both late targets are readable, in-bounds, and rectangle-disjoint at all seven widths. |
| D-4 | Medium | Yes | Home agent accessible names did not convey runtime, activity freshness, or health, and waiting-for-clarification was not independently exercised. | Added complete row names and distinct approval/clarification fixtures, including the visible clarification question and exact Console state. |
| D-5 | Low | No | A data-light installation leaves intentional open space in Focus, Live Agents, and schedule panels. | Accepted. Mentat shows honest empty/degraded states instead of invented activity; density will naturally increase with real tasks, agents, and calendar data. |

### Home correction reconciliation

| Root cause | Corroboration | Decision and evidence |
| --- | --- | --- |
| Legacy layout rules survived the new Home DOM. | C-1/C-3 and D-1 corroborated. | Accepted and fixed with bounded disclosures and complete Emerald/Classic grid contracts. |
| “Active” Console state was narrower than the actual Hermes run lifecycle and connection identity. | C-4, with product verification in D-4. | Accepted and fixed with waiting-state and exact-binding contracts. |
| Bounded Home lists need operational ranking and complete nonvisual meaning. | C-6 and D-2/D-4 corroborated. | Accepted and fixed with explicit status rank, text state, progress semantics, and richer names. |
| Minimum target width changes the schedule's visual collision interval. | C-5 and D-3 independently reproduced the same late-day failure. | Accepted and fixed by lane allocation over final visual intervals plus desktop and phone boundary fixtures. |
| Honest sparse states create whitespace. | D-5 unique and non-blocking. | Accepted as preferable to mock agents, jobs, tasks, or calendar events. |

### Final Home reverification

- Focused Home/visual/calendar/Console contracts: 60 pass, 0 fail, 0 skip.
- JavaScript syntax and `git diff --check`: pass.
- Browser smoke: `{"ok":true}` across 1680, 1440, 1200, 1024, 900,
  768, and 390 px, including Classic rollback, disclosures, run binding,
  agent ranking, approval/clarification, accessible names, arbitrary lanes,
  adjacent late events, and 44 px phone targets.
- Full suite: 783 pass, 0 fail, 4 platform-specific skips.
- Reviewer C final re-review: clean; no remaining blockers.
- Reviewer D final re-review: clean; no remaining blockers.
- Residual risk: manual Safari/Firefox and complete screen-reader validation.

## Documentation updates

- Roadmap: No update; this slice executes the already approved Emerald
  conversion plan without changing milestone scope.
- Changelog: Deferred until the slice is accepted for publication.
- Design system: Added `MENTAT_OPERATIONS_DESIGN_SYSTEM.md` with the layout
  anatomy, Figma-ready primitive and semantic variables, type/spacing/radius
  systems, component anatomy, interaction states, responsive rules,
  accessibility requirements, and visual QA checklist.
- Implementation plan: Added `MENTAT_OPERATIONS_IMPLEMENTATION_PLAN.md` with
  incremental conversion slices for Home and the five remaining product areas,
  data/behavior boundaries, test gates, rollout risks, and definition of done.
- Architecture/operator docs: No Hermes behavior-boundary change was required.
- Project/session notes: This review log.
- Documentation verification: Review log checked against the implemented diff
  and test evidence before adversarial review.

## Publication gate

- Proposed files: `MANIFEST.in`, `packaging/mentat.spec`, `public/app.js`,
  `public/core.js`, `public/index.html`, `public/styles.css`,
  `public/mentat-mark-emerald.png`, `pyproject.toml`,
  `scripts/browser_smoke.mjs`, `scripts/verify_python_artifacts.py`,
  `MENTAT_OPERATIONS_DESIGN_SYSTEM.md`,
  `MENTAT_OPERATIONS_IMPLEMENTATION_PLAN.md`,
  `tests/test_agent_console_attachments_ui.py`,
  `tests/test_calendar_week_ui.py`, `tests/test_frontend_workflow_feedback.py`,
  `tests/test_home_operations_ui.py`, `tests/test_packaging_cli.py`,
  `tests/test_visual_contract.py`, and this review log.
- Branch and base: `codex/emerald-foundation-shell` into `main`.
- Commit message: `feat: add Emerald shell and operations Home`
- PR title: `Add Emerald shell and reference-aligned operations Home`
- PR summary: Add the shared Emerald design system, saved
  theme/shell/contrast preferences, responsive accessible navigation shell,
  reference-aligned data-driven Home, packaged Mentat mark, conversion plan,
  and regression coverage while preserving the existing six-view and Hermes
  capability boundaries.
- Unresolved risks: Manual cross-browser and screen-reader validation remains;
  no known blocking functional or compatibility defect remains.
- User authorization and scope: Granted in this Codex task on `2026-07-25`
  for staging, commit, branch push, ready pull request creation, and merge.
- Commit hash: None.
- Ready PR URL: None.

## Outcome review

- Classification: Pass with caveat.
- Acceptance criteria summary: AC-1 through AC-15 passed.
- Potential bugs or untested paths: Browser automation covered Chromium at seven
  widths; a manual Safari/Firefox and complete screen-reader pass was not run.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: No data migration is introduced.
  Existing explicit color choices remain authoritative, and the saved Classic
  shell is the visual rollback.
- User decision: Accepted in this Codex task on `2026-07-25`.
- Next slice authorized: No
