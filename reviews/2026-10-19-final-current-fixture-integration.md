# Final current fixture integration

Base: 101c6d3. The initial source-only checkpoint restored the exact approved fa9fda3 webhook and main-database fixtures. Normal merge 08805f6 retains the approved fa9 QA ancestry, its three fixture corrections, and their evidence documents.

The webhook seed again uses canonical `todo` with explicit nullable task metadata. The main-database mutation test again checks the current typed error, exactly three captures and two existing pauses, and no temporary snapshot materialization. The watchdog fixture again uses its bounded readiness receipt before timed operations and proves both worker slots. All fourteen current cleanup tests and required imports remain intact. Production code, baseline, deadlines, skips, and all other fixture assertions are unchanged from 101c6d3.

The original 101 full run completed with exit 1: twelve shard summaries, 2,790 test runs, 130 existing skips, five failures and one error, with zero ResourceWarnings. Four permission-fixture assertions were affected by the caller inheriting umask 077: `mkdir(mode=0755)` created 0700 directories. The other two events were the missing canonical webhook seed fields and stale main-database mutation error assertion restored here. That original run and all its evidence remain preserved. Its source and all three standalone runtime trees were unchanged after completion.

The corrected caller sets umask 022 only on the test child; private parent directories, logs, and receipts keep their explicit private modes. The old fa9 record did not capture its umask, so no historical environment equality is claimed. The separate 101 mask-only preparation was never executed.

Focused verification ran once against exact 08805f6 with ResourceWarnings as errors, `-B`, fresh private HOME/Hermes/temp directories, native variables unset, and test-child umask 022. The signed local Kanban synchronization, main mutation across WAL capture, and DNS/total watchdog methods all passed: three tests in 1.747 seconds, no skips or warnings, authoritative exit 0 and unchanged source. This focused run did not repeat the four permission-fixture assertions or establish a full-suite pass.

Final publication checks are recorded separately against the final reviewed head. The earlier fa9 pass does not qualify this new branch. A complete full run with the reviewed fixture cohort and corrected caller, package verification, actual local journey, and native helper-origin verification remain separately scoped evidence.
