# Home load performance on the Project stack

## Contract and investigation plan

This branch starts at exact PR264 head
`667744984d3cf0b7a5458ece206075e924c21b2a`. Its hosted Node foundation job
118224513089 in workflow39300608851 passed browser smoke and all nonperformance
categories, but mobile Lighthouse scored94/94/94 against the unchanged95
median threshold. LCP was2949–2995ms. These are real current-head failures,
not canceled predecessor aggregations.

The bounded hosted artifact contains scores and timing only. It has no LCP
node, request chain or trace, so source guesses do not establish the cause.
Reproduce full reports with the exact pinned Chrome152.0.7923.0 and current
Lighthouse13.4.1, disposable data/config/home/Hermes/vault/browser profiles and
this branch's own dependency installation and build. No owner account, provider
or Run is involved.

Before changing rendering, compare the current producer tip2324cb1. That tip
already includes AppShell inactive-route prefetch control fromca638f5.
Determine whether that existing reviewed optimization addresses the measured
request/render delay. Preserve route contents, normal navigation, client
navigation hydration, accessibility and all current features. Do not replace
current architecture with a historical UI.

Only component/source changes under web/ and this review are owned here.
Dependencies, configs, workflows, smoke scripts, Lighthouse gate, score95,
three measured runs, category requirements, timeouts and budgets remain fixed.
Require comparable baseline/change evidence, focused behavior tests, full
lint/typecheck/test/build as appropriate and the unmodified Lighthouse gate.
Two independent reviews and current hosted CI are still required before merge.

## Existing source correction and baseline evidence

The complete AppShell blob from ca638f5 is already present on original267 and
later feature branches. Original264–266 lack it. This branch carries only its
two Link prefetch props, leaving every element, label, route and normal click
behavior unchanged. It does not cherry-pick the larger Task-input feature.
The resulting AppShell blob is `74e790330aca30a8963776e7cd51ef5e7ce365e1`,
identical to the existing producer tip's file.

Three full local pinned-browser mobile traces identify the unchanged initial
Home subtitle as LCP. Each baseline makes four speculative inactive-route RSC
requests during Home load, covering Agents, Tasks and Runs. There are26 total
requests. Baseline scores are99/87/95 and LCP1922/2793/2726ms. These local
runs overlapped other owned CPU work and do not reproduce or explain the
Linux94 median by themselves. Request elimination and unchanged content/
navigation must be verified separately from score variation.

Lint and typecheck pass. The first full local web run passed387/388 methods;
one pre-existing planning-ui test failed its initial Ship Alpha lookup after
six seconds. That test renders ProjectsTasksWorkspace directly and never
imports changed AppShell. Its exact focused rerun passes unchanged in734ms.
The original failure log is retained; a quieter full run and rebuild are in
progress. No assertion, test source, deadline or gate has changed.

Changed-source traces, the unchanged six-audit gate and real navigation smoke
remain pending. Passing local checks cannot establish the final exact-head
hosted95 requirement.
