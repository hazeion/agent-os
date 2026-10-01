# Browser smoke navigation readiness backport

PR #265 at `5d358c0` fails the installed-package browser test in
`inspectTwoHundredPercentReflow`: drawer-open times out after navigation.
The published job is
[109749003363](https://github.com/hazeion/agent-os/actions/runs/36672066561/job/109749003363).
Package construction and startup precede the failure; this is not evidence
of a missing wheel module.

Replay only the already reviewed browser-script part of `aa53cb2`. The original
file is byte-identical to that commit's preimage, and the corrected file is
byte-identical to its reviewed result. A document can remain complete while
Page.navigate starts a new navigation. Mark the outgoing document, require the
exact target URL and a different document before accepting shell readiness,
then require the existing bridge-ready state before clicking the zoom drawer.

Every viewport, drawer, reflow, semantic and accessibility assertion and every
existing wait deadline remains unchanged. No application, data/schema, browser
authority, provider operation or owner server is changed. Validate JavaScript
syntax and the navigation race with an isolated stubbed CDP document transition:
the old real navigate function accepts the outgoing complete document on its
first poll, while the corrected real function rejects it and accepts the new
document on its second poll even when the target URL is unchanged. This probe
uses only an in-memory DOM/CDP stub, not an owner browser/server or a claim of
hosted browser acceptance. JavaScript syntax and diff checks pass. Obtain
independent compatibility reviews before updating the full PR.
The next hosted package/browser run remains unverified until completion.
