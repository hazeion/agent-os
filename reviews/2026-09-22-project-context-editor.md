# Project context editor and explicit Agent access

Scope: [Project editor and grants](https://github.com/hazeion/agent-os/issues/261).
Baseline: `43d612d`, reviewed storage and confirmed-deletion integration.

Implement the approved context contract through the existing Projects & Tasks
workspace. Owners edit a brief, stage validated files, explicitly publish an
exact version, inspect history and grant/revoke access for selected canonical
Agents. Permission changes never start work. Runtime qualification and exact
Task/Run input admission remain the next slice.

Authority work comes first: private Agent incarnation, exact version-bound
grant preview/confirmation, revision-bound revocation, revocation on Project
retirement or Agent deletion, and restore-time invalidation. Keep all new
metadata within the existing shared budget. Staging is Project-owned and
disposable; deletion removes it, and backups must discard it. A staged ID alone
does not authorize publication in another Project or after deletion/recreation.

The UI uses fixed authenticated, CSRF-protected Node/Python capabilities. File
reads require exact retained context membership or Project-owned staging, with
bounded validated content and no browser paths. Eligible historical pruning
requires an exact preview/confirmation and cannot remove current, granted or
Run-pinned context. Retired history stays separate from reused Project IDs.

Required tests cover grant/edit/revoke races, stale confirmations, Agent and
Project ID reuse, restore revocation, staging scope/expiry/capacity, file reads,
protected pruning, owner admission/CSRF, and rendered desktop/mobile workflows.
Two independent whole-slice reviews and fixes until clean precede publication.
Status: implementation in progress; no new capability advertised yet.

## Authority work in progress

Schema 28 and `project_context_access.py` now provide private Agent incarnations,
exact preview/confirmation, context-and-revision-bound revocation, atomic
retirement/deletion revocation and restore invalidation. Initial tests cover
identity reuse, stale previews, no implicit grant/Run creation and quota bounds.

Early review reproduced preview replay after restore and restore-time metadata
growth. A private approval epoch and terminal-state quota reservations address
those. A boundary test fills the genuine schema-27 context budget exactly and
creates 128 Agents, then validates migration, retirement and restored backup.
The bounded 64 KiB control allowance preserves those previously admitted roots.

Before this slice can publish, production interrupted-restore recovery needs an
attempt-stable sanitization context. The current restore receipt protocols 2/3
have no sanitizer time/seed, but exact resume compares regenerated private
digests. Fresh timestamps/epochs would therefore mismatch after publication.
Protocol 4 now persists time/seed and the sanitized digest before live writes.
Interruption/resume tests cover publication, old-tree cleanup and receipt
removal; repeated fresh restores produce distinct epochs. Historical owner
receipts are recognized only by a bounded timestamp witness from sanitizer-owned
fields followed by exact whole-unit replay. Their complete published tree is
the durable witness during cleanup. Unrelated valid credential metadata changes
are rejected. Direct sanitizer tests alone do not prove this lifecycle.

Staging, explicit permissions and history pruning are implemented in private
Python capabilities and connected to the Project editor. Rendered browser
acceptance and whole-slice reviews remain pending. The branch is work in
progress and has no PR yet.

Current targeted verification: 43 context/access/deletion tests pass. A virtual
empty snapshot initially changed identity because migration 28 generated fresh
entropy during each read-only capture. Temporary empty-unit initialization now
uses a deterministic non-authoritative zero marker; validation permits it only
without contexts/grants, and first context publication activates fresh entropy.
This restores stable ordinary backup/restore previews. The new production
restore suite passes all five cases, including three interruption points,
changed live tree/seed rejection, unsubmitted-preview invalidation and a genuine
protocol-3/schema-27 active-owner publication using a real timestamp. Both
independent restore reviews are clean. The broader backup/access run passes
41 tests (two platform skips); the full private-state suite passes 53 tests
(one platform skip).

Metadata-only maintenance now permits unavailable historical bytes so the owner
can revoke access or publish an explicitly verified replacement. Grant previews
and confirmation still read and verify every selected file; backups still
require every retained file. A focused missing-history regression proves
revocation/replacement succeeds while backup refuses the missing historical
content. The recovery UI remains to be connected.

## Preparation and website boundary

Staging binds exact Project revisions, checks deduplicated file capacity and
expiry, and publishes only an exact selected/staged set. Reads check staging or
immutable-version membership. Pruning blocks the current live version and
active grants, preserves shared Run files, and retains revoked grant tombstones
to prevent revision-reset replay. Independent authority review found no blocking
defect in those helpers. Thirteen Python editor/private-HTTP tests pass.

The editor permission projection joins the current private Agent incarnation
and caps the result at the registry's 128-Agent bound. A deletion/recreation
regression verifies that old tombstones are retained privately but cannot appear
as the replacement Agent's permissions. Active grants project a null reason;
the first gateway review caught a TypeScript mismatch, now corrected with both
Python-projection and browser-contract regressions.

The website now has thirteen named operations across eleven fixed routes for
editor/history reads, verified file downloads, uploads, publication, discard,
grant preview/confirmation, revoke and prune preview/confirmation. They use the
shared owner-session/CSRF wrapper before parsing; private reads stay GET, and
all responses are bounded and checked against exact public shapes. Downloaded
text is forced inert and uncached. Full-size upload, private-field rejection,
path/body binding, transport and route tests pass (eleven focused web tests),
as do TypeScript and focused lint. The gateway correction and route factory
have a clean independent re-review; whole-slice review is still required after
the UI and rendered desktop/mobile acceptance are complete.

## Owner editor

Projects & Tasks now offers an explicit Open context control, brief and file
selection, version publication, saved-version inspection, Agent access previews,
confirmation and revocation. Retained Project history is separately accessible
after deletion and has exact removal previews. File reads use only the version
or Project-stage membership routes. None of these actions dispatches work.

UI review caught unsaved draft loss when switching Projects. Drafts now live in
the workspace per Project; late reads cannot replace another editor, and late
upload/discard completions update only their original draft. Confirmed deletion
clears that Project's draft. A clean re-review follows six passing rendered DOM
tests covering grants/revoke, unchanged permissions after publication, failed
save preservation, retired history, A-to-B-to-A navigation with a pending read,
and upload completion after navigation. Production browser visual/interaction
acceptance is still outstanding.

Current checks: all 403 web tests pass, 25 focused Python access/editor/HTTP tests
pass, TypeScript and full ESLint pass, and the production Next build passes.
The first full web run identified the expected keyboard-order assertion change
for Open context; the updated test explicitly tabs through that new button.
The final all-web run is clean. Whole-slice authority review has been requested;
package checks, broader migration coverage and browser acceptance remain before
publication.

## Final acceptance and quota correction

Whole-slice authority review found that actual Agent identity occupancy was
charged without enforcing the context quota on later registry creation. Context
admission now reserves all 128 maximum-size identity slots. The boundary test
admits a graph at its exact charged capacity, adds 127 maximum-length Agents to
the existing one, and validates context and backup. All 13 access/migration
tests pass, including the full schema-27 metadata migration case; re-review is
clean. A further 64 context, editor, HTTP and forward-migration tests pass.

The built Next dashboard and real Python/SQLite context authority now pass the
desktop (1280 px) and mobile (390 px) browser workflow: text-file staging,
publication, exact Agent preview/confirmation, revocation, and retained-history
view/removal. The fixture recreates a deleted Project ID and verifies its old
history remains separate. Both layouts have no horizontal overflow; captured
screenshots were inspected. The harness initially selected the wrong dropdown,
then compared CSS-capitalized summary text literally; corrected label selection
and normalized visible-text matching resolve those harness failures. Browser
checks run in the Node quality job. Unrelated runtime integrations are inert;
no live Agent execution or real owner OAuth acceptance is claimed here.

Wheel/sdist build and exact artifact verification pass. The final package refresh
includes the last UI styling/disclosure changes. Both authority and gateway/UI
whole-slice reviews are clean after corrections. The browser CI step uses the
job's verified pinned Chrome installation. Parent PR 265 currently
has two unresolved CI failures: Windows Python 3.12 group 2 timed out reading
the first Conversations response, and mobile Lighthouse scored 94 against 95.
Logs are retained locally; aggregate evidence does not establish root cause.
Do not report the parent stack as green or merge-ready.

The final wheel/sdist refresh and exact verification pass. An isolated installed
wheel smoke verifies upload, publication, grant, safe editor projection and
backup/restore validation without importing the source checkout. Windows
path-normalized secret diagnostics report no new findings; Linux CI remains
the authoritative raw scan gate.
