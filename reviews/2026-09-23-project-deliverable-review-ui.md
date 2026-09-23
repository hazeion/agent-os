# Project result review website

Status: implementation reviewed; full PR pending.

The authenticated owner website exposes fixed Project review status, preview,
and confirmation routes over the Python decision authority. The owner reviews
all three saved garage result types together. Acceptance covers the complete
bundle; a change request selects affected result types and records a bounded
note. The explicit confirmation shows the current exact version and content
of each result. It never starts Agent work or claims generated provenance.

A preview from the server is shown only when its Project revision and all
three head versions match the validated content already displayed to the
owner. A newer version returns the bundle to pending review. Definitive stale
confirmations clear the preview, while uncertain delivery leaves the exact
preview available for idempotent retry. Status fetch failures hide decision
controls. Refreshed change requests retain their selected result types.

The Python bridge and Node gateway allow only named operations behind owner
session and mutation-CSRF checks. Browser and bridge contracts reject extra
fields, malformed IDs and widened runtime authority.

Independent read-only reviews: reviewer A identified the unseen-newer-head
confirmation risk; reviewer B identified missing content disclosure, lost
affected-slot scope and stale-status handling. Those issues were fixed and
both reviewers reported no remaining actionable concern on re-review.

Verification: 14 focused Python bridge and review-storage tests, 443 website
tests, TypeScript and focused lint pass. The production website builds. The
built desktop and mobile garage journey passed in Chrome, including both
decision actions and no horizontal overflow. The wheel and sdist build and
package verification passed.
