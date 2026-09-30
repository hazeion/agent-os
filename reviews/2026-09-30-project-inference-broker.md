# Durable Project inference broker core

Connect the fixed worker frontend to exact prepared input derivation and the
schema-43 call journal. The initial backend is an explicit synthetic
qualification responder, not a live provider factory. No browser route,
credential resolution, provider URL, real model call or Run admission is added.
Production requires the separate immutable release/model/credential boundary,
durable scope admission and output provenance gates. Proposal SQL guards stay.

Derive one bounded deterministic query and optional native image from the exact
schema-42 receipt, context and planning-input version. Validate the shared graph,
live grant and selected file order/kind/MIME/size/digest, then read bytes through
the existing no-follow attachment boundary. A missing or changed item rejects
the entire input set. Respect the namespace 1 MiB query/8 MiB image ceilings and
the journal's smaller applicable policy. Retain no raw input in a sidecar.
Preparation and every current-work/cache gate also require the existing
canonical Run-store authority receipt and complete private archival Run
validation. A populated unclaimed or malformed store cannot prepare inputs,
spend a call or return cached text.

Worker bodies are bounded evidence, not provider instructions. Validate one
exact prepared user query/image, the frozen model, streamed/no-tool request,
supported field/role/content shapes and finite request size. Construct a new
host-owned fixed proposal system/user request with the immutable model and
max_output_tokens; no tools, streaming, worker system, headers, endpoint or
worker-selected inference parameter reaches the backend. Bind the normalized
worker evidence and actual constructed request in one request digest.

Under the private lock, reserve one call and commit. In a separate guarded
transaction, mark it unknown with the exact first host-held token and commit;
verify committed readback before starting the synthetic response. Duplicate,
changed-body, reserved-after-crash and unknown-after-crash paths never invoke
the backend. Only constant-time synthetic acceptance is linearized under the
fence/private/scope locks after commit; response waits run outside those locks,
and this helper has no network operation. Its responder retains at most one
constructed request. A real backend must separately prove bounded acceptance
and credential/network work outside the private-state lock.
Known outcomes are normalized through the journal; commit errors remain
unknown. No retry or work refund exists.

A per-broker submission fence linearizes Stop against beginning work; after
Stop returns no new submission can start. Already in-flight work may retain
truthful late outcome accounting, but cannot become a live result after Stop,
grant revocation, scope exit or restore. Replay also requires exact live
epoch/grant/input/binding and owned scope readback. This component's synthetic
fence is not a durable Run Stop/admission receipt; a new production factory must
prove those before using any real provider. Cached text is not Run success,
generated-output registration or owner Apply authority.

Use only scoped synthetic runtimes and fake responses for initial integration
tests. Cover exact input preparation, missing/changed bytes, malformed worker
requests, canonical output-token limits, duplicate/conflicting body, crash
windows, concurrent first requests, commit failures, unknown response, Stop,
late settlement, revoked/restore replay, and the real namespace/stock-CLI wire
with durable journal readback. Obtain two independent reviews, fix findings,
then publish a full PR. Keep complete runtime/garage acceptance open.

Final actual Linux broker/journal/namespace/scope group: all 78 tests pass,
including 25 broker methods, unchanged official 0.21.5, accepted canonical PNG
delivery through fixed stock image annotation handling, one synthetic response
and durable known/debit readback. Windows passes 24 broker methods and skips
the Linux-only stock integration. Six before/after-commit failure windows,
concurrent first requests, Stop/late historical settlement, exact input bytes,
oversized/non-text versus unknown outcomes, authority and backup are covered.

Independent reviewers found immutable-policy/effective-scope mismatches,
missing/nonfinite scope deadlines (including after construction), and absent
canonical Run-store authority validation. All were corrected with refusal
regressions before debit/work; the malformed receipt uses a valid-SQL nonhex
digest to exercise the real validator. Both final independent re-reviews are
clear. These tests establish fake-backend controller bookkeeping only, not live
provider readiness, consent, Run dispatch or a complete garage journey.
Final wheel and source builds pass exact public-member/RECORD verification;
the installed broker bytes match the reviewed source exactly.
