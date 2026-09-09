# Fresh-install and new-user acceptance audit — September 9, 2026

**Verdict: hold publication.** The installation and many planning operations work,
but the complete task → result → revision journey is not yet smooth. This audit
records findings; it does not implement fixes or approve a push.

## Candidate and method

- Cloned `https://github.com/hazeion/agent-os.git` into a new independent checkout.
  Published `main` resolved to `e1081c4` (durable owner authority). The unpublished
  QA candidate was imported locally and checked out at `3ebb76e`. No QA commits
  were pushed. This tests the candidate, not an already-published release or the
  eventual candidate integrated with current `main`.
- Created a fresh virtual environment and installed `requirements.txt`, ran the
  interactive setup wizard, installed the frozen web dependencies, built the
  production dashboard, and launched through `run.bat` on isolated port 8897.
  Python 3.13.1, Node 24.19.0, and installed Codex CLI 0.153.4 were used. The
  machine already had a Codex sign-in; new account authentication was not tested.
- The README's unqualified Windows `py` command would select installed Python
  3.14.6. The audit explicitly selected supported Python 3.13 and records this
  prerequisite/documentation problem rather than silently calling the exact
  README sequence successful.
- Fresh Mentat data came from the packaged seed. Projects, Tasks, assignment,
  edits, Runs, Conversations, review actions, and deletion were all performed
  through the production browser UI. No backend-created Tasks or Agents were
  substituted for missing product flows.
- Inspected desktop 1440×900 and 1920×1080, phone 390×844, and narrow phone
  320×740. Used rendered screenshots, keyboard interactions, accessibility state,
  and read-only DOM measurements. Phone tests simulate viewports, not a physical
  phone, touch keyboard, or remote browser access.
- Two independent review-agent subagents verified bounded source paths behind
  findings. They did not change code, run the browser, or publish anything.

## Confirmed findings

### F01 — P1: update dependencies before publication

Fresh `npm ci` reports three vulnerable packages: `next` critical, `sharp` high,
and development dependency `js-yaml` high. The production-only audit reports
one critical and one high package. The locked Next version is 16.3.2.

The [Windows-hosted Next advisory](https://github.com/advisories/GHSA-p293-qw3h-jr36)
lists 16.0.0–16.3.2 as affected and 16.3.3 as patched; the audit offers 16.3.4.
Also review the [Next AVIF advisory](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4)
and [sharp/libheif advisory](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c).
These are dependency audit findings, not evidence of exploitation. No exploit
was attempted; applicability of every image-processing path was not established.
Update the lockfile deliberately and rerun build, package, security and UI gates.

### F02 — P1: idle Codex follow-ups lose Conversation context

Reproduction: ask Home for a five-section workshop agenda. The visible answer
gave durations **5, 8, 10, 15, 7** minutes. After completion, ask: “In the agenda
you just wrote in this conversation, what were the five section durations, in
order? Reply with the five numbers only.” The answer was **0 0 0 0 0**.

Source verification: ordinary idle submission in `orchestration_service.py:1821`
does not pass `continuation_runtime_run_ref`. The new Run consequently starts a
new Codex thread with only the new objective. Queued continuation passes the
predecessor reference, so behavior depends on when the user presses Send.
This predates the QA changes. Preserve the same Conversation's bounded,
verified continuity for ordinary follow-ups as well as queued ones.

### F03 — P1: Task Run results cannot be read before acceptance

Created “Draft a workshop agenda,” assigned Direct Agent, entered a complete
objective, moved to Planned, and confirmed Run once. Codex completed. The Runs
timeline exposed only “Codex responded”; the Task inspector then offered
Accept and Request changes without an answer or result link.

Source verification: `projects-tasks-workspace.tsx:1441` contains no answer
presentation. `server.py:4797` permits timeline content for trusted Vercel
messages only. Task Runs do not create Console Messages
(`run_repository.py:5074`). This predates QA. Add a bounded authoritative result
presentation; do not expose raw private provider payloads as a shortcut.

Acceptance was exercised solely to verify the stage transition. It did not
constitute content review of the inaccessible Task Run answer. Home separately
displayed a complete successful answer to an explicitly supplied prompt.

### F04 — P1: Request changes feedback is not sent to the next Task Run

Submitted feedback: “Please make the workshop suitable for phone cameras and
include one lighting exercise.” The Task returned to Planned and allowed a
second Run. Its next preview gave no readable objective/feedback summary.

Source verification: the feedback is retained in a review receipt
(`run_repository.py:1875`), but the next objective comes only from the Task's
description/title (`orchestration_service.py:280`); the Codex prompt adds only
acceptance criteria (`codex_runtime.py:1305`). Without manually editing the
description, that feedback never reaches the next Run. This predates QA.

### F05 — P2: selected Task execution does not advance automatically

The first Task Run completed at 12:08:51 local time, yet its Task page continued
to show `dispatched · running`. The second completed at 12:10:49 but was still
reported Running several minutes later. Opening each Runs timeline caused the
canonical reconciliation; reselecting the Task then revealed review controls.

The Task execution read is SQLite-only (`server.py:4978`) and the browser loads
on selection/mutation rather than completion (`projects-tasks-workspace.tsx:627`).
There is no execution Refresh or Open Run link in that inspector. This predates
QA. Provide bounded reconciliation and refresh through completion, with an
obvious route to the corresponding result.

### F06 — P2: Run cards contradict completed timelines

On both desktop and phone, the same Run card said Running and “Completed Not
completed,” with Send message and Stop controls, while its open timeline already
showed Run Completed. Pressing the page's Refresh corrected the card.

Timeline handlers update only events, not `renderedRuns` or the card snapshot
(`shell-runtime.js:878`, `shell-runtime.js:650`). This predates QA. Keep the
card and its action availability consistent with reconciled terminal state.
Existing server checks still refuse stale actions.

### F07 — P2: inspector title and actions can hide under the top bar

After editing at phone width, cancelling, and resizing to 1920×1080 with retained
page scroll, the inspector header occupied y=5.4–72.3 while the sticky utility
bar occupied y=0–64. Its title and Edit control were mostly covered. Whole-page
scroll can put the pane in the same position.

`globals.css:850` does not reserve the utility bar's clearance. The insufficient
outer offset predates QA, but batch 6 newly places primary Edit/Save actions in
this header, exposing them to the overlap. Preserve visibility when scrolling
both the page and the inspector, including responsive transitions.

### F08 — P2: 320px phone layout overflows or clips horizontally

At 320×740 with a Windows scrollbar, available document width was 305px but
scroll width was 320px. Both root and body enforce `min-width: 320px`
(`globals.css:36`, `globals.css:41`); the main area and header extend 15px beyond
the available width. At 390px, client and scroll widths both measured 375px.
This width floor predates QA. Account for the scrollbar without clipping content.

### F09 — P2: Windows instructions can select unsupported Python

README's `py -m venv .venv` chooses this host's Python 3.14 despite installed
3.13 and declared support `>=3.11,<3.14`. Installing only requirements does not
enforce Mentat's package metadata, and setup/launch do not reject that version.
Use an explicit supported interpreter or a clear preflight. Pre-existing.

### F10 — P2: setup wizard omits the remaining source-build steps

The wizard's final “Next step” directs the user to `run.bat` before mentioning
Node dependency installation/build, although README runs the wizard before those
steps. A fresh unbuilt checkout would report `standalone_build_missing`.
The audit continued with the remaining README steps and built successfully.
Source-verified, pre-existing (`scripts/mentat_setup.py:613`).

### F11 — P2: runtime guidance uses an uninstalled console command

New Agents setup says `mentat vercel --help`, but the documented source workflow
installs dependencies only and creates no `mentat` executable in the fresh venv.
Use `python -m mentat.cli vercel --help` or document package installation.
The Agents instruction is introduced by QA (`agent-setup-panel.tsx:10`). The
wizard's `mentat connection status` instruction has the same pre-existing issue.

### F12 — P2: Windows file-execution limits need clear setup guidance

README advertises files/Context Packs while listing Windows as a primary beta
platform. Native Windows lacks the required descriptor-relative no-follow
cleanup capability; supported file execution correctly remains disabled.
Document the limitation and actionable supported alternatives. Do not weaken
that boundary. Source-verified pre-existing guidance gap; no real Hermes
installation was available for a positive file-execution test.

### F13 — P2: moving between Tasks and Runs loses the working selection

After manually selecting the workshop Project/Task and visiting Runs to inspect
its completion, choosing Projects & Tasks returned to the seed Mentat Project
with no selected Task. The user had to find both again. Home's explicit planning
attention deep link did correctly restore the target. Preserve normal working
selection and provide direct Task ↔ Run navigation. Observed on the candidate;
not claimed to have been introduced by QA.

### F14 — P3: fresh seed data gives misleading completion/attention signals

Home immediately surfaces “Review sessions and replay view” as review/needs
attention, while Tasks shows the same example as Done. Its seed record retains
attention flags despite completed status (`data/tasks.json:27` and flags below).
This is a pre-existing seed inconsistency, not evidence that Task refresh failed.
Clean the example rather than altering general attention semantics blindly.

## Additional observations needing focused reproduction

- Immediately after Stop and cancelling a queued Turn, the visible transcript
  lacked the just-submitted/stopped prompt and cancelled queued text even though
  recovery/queue controls updated. Reopening the Conversation restored both.
  No durable loss was observed; the root cause and introduced/pre-existing
  classification are unconfirmed. Investigate transcript refresh ordering.
- Queued messages split a Run's chronological transcript into separate groups,
  so Run 4/Run 5 headings recur later in the same Conversation. Source review
  confirmed contiguous grouping, not duplicate execution. Consider clearer
  continuation labeling as presentation polish.
- Run lists rely heavily on raw IDs, protocol-like status text, and ISO times.
  Task names and readable time/status copy would help users connect their work
  to the output. This should accompany F03/F05/F06, not be mistaken for another
  runtime failure.

## What worked in this audit

| Area | Observed outcome |
| --- | --- |
| Download, isolated install, build, run/stop scripts | Passed with the explicit Python correction described above |
| Project create, rename, archive, restore | Passed, including phone interaction |
| Task create, Agent assignment and due date | Passed; separate creation also passed at 390px |
| Description, priority, estimate, tags, Today | Saved and remained visible |
| Checklist titles, blank-title validation, completion | Passed; focus moved to new checklist inputs |
| Dependencies, map selection, zoom/fit controls | Passed; 32px controls and 16px green foreground icons |
| Board arrows and keyboard End | Final stage reachable without page-wide overflow at tested ordinary widths |
| Someday and return | Correct view membership; retained workflow stage |
| Manual Planned/In progress/Waiting/Review/Done | Passed for the manually managed Task |
| Daily recurrence | Next-day successor appeared immediately; search distinguished dates and stages |
| Reminder | Saved 10:30 AM America/Los_Angeles; summary displayed Sep 11, 2026, 10:30 AM PDT |
| Search and mutation refresh | Deletion and Project rename appeared without manual reload |
| Task Run once and acceptance | Runtime completed; acceptance moved to Done, subject to F03's missing result |
| Home answer | Complete five-section agenda and materials list visibly returned |
| Queue edit and automatic continuation | Edited queued follow-up ran and returned two requested bullets |
| Live `/steer` | Exact Run accepted steering and subsequently displayed the requested accessibility checklist |
| Stop and queue cancellation | Confirmed Stop produced Stopped; pending Turn became Blocked: Stopped; Cancel succeeded |
| Stale Stop confirmation | Refused honestly when the Run changed; no automatic retry |
| `/help`, `/model`, `/new`, unknown command | Worked; unknown command preserved the full draft |
| Conversation rename/archive/restore | Passed; first Apply after restore succeeded and retained an unsent draft |
| Tab closing | Presentation-only; Conversation remained in history |
| Focus/selection styling | Green focus rings and selected states were consistent at 1440, 1920, and 390px; layout exceptions are F07/F08 |
| Task deletion | Two disposable test Tasks removed without ghost cards/search results |
| Full Project cascade deletion | Deleted exactly 1 Project, 2 Tasks, 2 Conversations, 8 Runs, 0 artifacts; Home and Runs subsequently empty of audit work |

The reminder-summary concern raised during exploration was a false alarm:
the saved schedule appears under Planning details separately from its controls.
Locator/date-entry automation limitations were not classified as product bugs.

## Limits, cleanup, and next order

- No Hermes CLI, connected Calendar, configured Obsidian vault, or Vercel
  credentials were present in the fresh setup. Their unavailable states were
  inspected; positive delegation, provider switching, note/calendar linking,
  uploads, Context Packs and generated-file execution remain unqualified.
  Browser notifications were blocked; actual delivery was not verified.
- This was a Windows production-browser audit, not macOS/Linux CI, physical
  device testing, or exhaustive validation of every runtime and integration.
- The synthetic audit Project and its entire graph were deleted through the UI.
  Temporary viewport overrides were reset, the audit tab closed, and the owned
  port-8897 server stopped. The existing port-8894 QA preview/data were separate.
- No source fixes, push, PR, issue creation, or issue closure occurred during this
  audit. Raw local install/audit logs remain in the isolated checkout.

Recommended next order:

1. Reconcile the candidate with published `main` at `e1081c4`, update affected
   dependencies, and verify the combined authority/build boundaries.
2. Fix F02 Conversation continuity and F03/F04 Task result/revision behavior.
   These require explicit bounded runtime/data contracts, not UI-only patches.
3. Fix F05/F06 live state and F13 navigation using those result contracts.
4. Fix F07/F08 layout and F09–F12 onboarding/support guidance; clean F14's seed.
   These can run alongside core work with separate file ownership.
5. Reproduce the transient transcript observation, run independent reviews,
   repeat this fresh-install desktop/phone journey on the integrated candidate,
   then publish only after the acceptance condition is actually met.
