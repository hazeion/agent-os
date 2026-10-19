# Home load performance on the Project stack

## Contract and source correction

This branch starts at exact PR #264 head
`667744984d3cf0b7a5458ece206075e924c21b2a`. Its hosted Node foundation job
118224513089 in workflow 39300608851 passed browser smoke and every other
Lighthouse category, but mobile performance scored 94/94/94 against the
unchanged median requirement of 95. LCP was 2949–2995ms. This was a real
current-head failure, distinct from canceled predecessor aggregations.

The existing producer tip already includes AppShell inactive-route prefetch
control from `ca638f5`. Exact blob inspection confirms original #264 lacks it.
Original #265 and #266 already contain the identical source through earlier
`fc5ba51`; first ancestry containing `ca638f5` is not the first occurrence of
that source. Those descendants require ancestry/document propagation only.
This branch carries only its two Link prefetch props into #264.
Every element, label, route, accessibility attribute and normal click behavior
stays intact. Active/current-page links retain their existing default. The
complete AppShell blob is `74e790330aca30a8963776e7cd51ef5e7ce365e1`, identical
to the later source. The larger Task-input feature was not cherry-picked.

Dependencies, configuration, workflows, smoke scripts, Lighthouse gate,
three measured runs per mode, category requirements, timeouts and budgets are
unchanged. No new production capability, provider operation or Run is involved.
Root and ci_review_two independently cleared source commit
`0e12af49612a2ed5947c8022cea004df8078e7ec`. Subsequent evidence changes are
this document only. Exact-head hosted CI remains required before merge.

## Full reports and measured behavior

The hosted artifact has scores and timing only, with no LCP node or trace.
The isolated worktree installed its own locked Node dependencies, built its
own dashboard and downloaded the exact public project-pinned Chrome
152.0.7923.0 into new temporary storage. Experiments used disposable data,
config, home, Hermes, vault and browser-profile roots, with the real CLI,
Python bridge and built Next app. Owner state and active profiles were unused.

Three full mobile reports per variant identify the same initial Home subtitle
as LCP, with identical text, selector and geometry. All baseline reports show
four speculative inactive-route RSC requests during Home load, covering
Agents, Tasks and Runs. All changed reports show zero. Total requests fall
from 26 to 22; first-report transferred bytes fall from 255752 to 246668.
This is direct request evidence, not a claim derived from score noise.

| Evidence | Mobile scores | Meaning |
| --- | --- | --- |
| Hosted original #264 | 94/94/94 | Existing exact-head gate failure |
| Local baseline full traces | 99/87/95 | Diagnostic, shared CPU contention; not a Linux reproduction |
| Local changed full traces | 94/95/94 | Diagnostic; does not itself pass the median requirement |
| Unchanged local six-audit gate | 95/95/95 | Actual local gate passes its unchanged median requirement |

The changed diagnostic LCP values are 2771/2667/2707ms. Their nonperformance
categories all score 100. The trace still identifies normal script/layout
work and one render-blocking stylesheet. No subtitle, visibility, animation,
font, content or timing workaround was added. The existing source correction
is retained without claiming a universal timing gain.

After coordinating other owned heavy work to pause, the unmodified gate ran
once on the changed source. Its three desktop scores are 100/100/100 and mobile
scores are 95/95/95. Every accessibility, best-practices and SEO score is 100.
The gate verifies Chrome 152.0.7923.0 and Lighthouse 13.4.1, retains three runs
per mode and the existing minimum of 95, and reports `ok:true`. This is the
first full gate invocation after the carry, not a retry-until-green sequence.
It proves local gate behavior, not future hosted results or excess headroom.

## Checks and limitations

ESLint, TypeScript, all 388 web tests and the production standalone build pass.
The first local full test run passed 387/388; one existing planning-ui test
failed its initial Ship Alpha lookup after six seconds. It renders
ProjectsTasksWorkspace directly and never imports changed AppShell. The exact
focused test passes unchanged in 734ms, and the subsequent quieter full run
passes all 388 tests without skips. Original failure evidence is retained.
No assertion, test source or deadline was changed.

Both existing real-browser modes pass on tested source `0e12af4`: default
route/desktop/mobile/keyboard/reflow/planning smoke and client-navigation
persistence with pre-hydration navigation. No smoke code changed. Every owned
app/browser process closed after each experiment. Reports and traces remain in
private temporary storage, with concise logs at:

- `/private/tmp/mentat-planning-performance-baseline.log`
- `/private/tmp/mentat-planning-performance-after.log`
- `/private/tmp/mentat-planning-performance-final-gate.log`
- `/private/tmp/mentat-planning-performance-navigation.log`
- `/private/tmp/mentat-planning-performance-check.log`, original failed run
- `/private/tmp/mentat-planning-performance-check-quiet.log`, complete passing run

No real provider, Google login, remote HTTPS host, Linux runtime qualification,
physical-device acceptance or garage work is proven here. Current hosted CI,
including the same performance budget, remains an integration gate.

The guarded child preparation confirmed both original and currently published
#265/#266 AppShell blobs already equal `74e79033`. Its initial exact-two-file
expectation stopped before commit when only this document was staged. The
history statement above corrects the earlier ancestry-based assumption;
child merges retain zero production delta and the same original heads.
