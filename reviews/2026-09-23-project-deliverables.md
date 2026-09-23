# Project deliverables: owner storage foundation

Status: implementation in progress; this slice does not complete issue 263.

Schema 31 assigns every Project a private incarnation and retains three typed
result slots: dimensioned layout, linked products, and ordered implementation
steps. Owner edits create immutable numbered versions. Layout coordinates are
bounded in millimetres and render a PNG from the exact saved data. Product
links are inert, validated public HTTPS destinations; no server fetch, purchase
or external message occurs. Missing or invalid dimensions fail before saving.

Preview PNGs use the existing private attachment store and become retained
roots only with their version. A stale request fails before staging. A failure
after staging releases the temporary preview; an uncertain committed version
remains protected by its reference. Project and Task deletion previews bind
and disclose retained deliverable counts. Confirmed Project deletion retires
the old slots; Project ID reuse starts a fresh incarnation. Ordinary Project
renames, additions and reorders update existing rows in place so they cannot
retire live results.

The schema reserves historical Run and Task provenance fields but does not
accept generated versions. Source Run text and a future receipt digest can
survive Run pruning without pretending the Run is live. An exact registered
output, successful Run, matching input receipt and bounded content must be
verified before any generated promotion is implemented. Exact-version owner
acceptance, coordinated revision requests, pruning and the website editor also
remain open in issues 263 and 240. This foundation makes none of those claims.

Two independent reviews are clean after fixes to Project incarnation
preservation, malformed layout fields, obfuscated loopback links and failed
PNG staging. A broad affected Python run passed 215 tests (21 platform skips),
the forward-migration group passed 72 tests, and the final storage/Project/
deletion group passed 41 tests after corrections. All 417 web tests,
TypeScript, ESLint and the production build passed. The built desktop/mobile
garage workflow passes against disposable Python/SQLite data. The wheel and
source package pass exact artifact verification, and an isolated wheel import
renders a schema-31 garage preview. A sample 6 m × 5 m layout PNG was inspected
visually; it represents the supplied dimensions and placements only.
