# Windows CI shard capacity

Status: implementation reviewed; hosted CI pending.

The Windows matrix still covers all unittest modules exactly once, but two
stacked PRs reached the 30-minute group watchdog while tests were passing.
PR #272's Python 3.12 group 3 was in the owner-methods module with four units
remaining; PR #273's Python 3.11 group 10 was in the Project-plan module with
three units remaining. Neither failure log reports a failing assertion. The
remaining slow modules make a rerun alone an unreliable repair.

The fixture-free Task repository module is now split into its 58 discovered
test cases and distributed by the existing deterministic weighted partitioner
across the same 12 groups. In the recomputed PR #272 inventory, group 3 no
longer contains the seven-minute restore-sanitization module or the entire
Task repository module; PR #273 group 10 no longer contains Project plans.
The group watchdog rises from 30 to 40 minutes,
with a 50-minute Windows job ceiling for installation and compile overhead.
No test is skipped, removed, or given a different assertion. The existing CI
contract verifies that every discovered test appears exactly once, split
modules have no class/module cleanup fixtures, and the shard weights stay
balanced. The seven focused CI workflow tests passed locally. Two independent
read-only reviews found no remaining actionable defect.

Hosted Windows checks are required to verify the actual duration and package
environment before the parent PR can merge. If a group still reaches its new
watchdog, inspect its per-unit timing rather than raising the limit again
without evidence.
