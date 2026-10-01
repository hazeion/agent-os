# Project results website editor

Status: owner-authored website flow in progress; this does not complete
generated deliverables or issue 263.

The Project results panel edits measured layout dimensions and placements,
public product/source links, and an ordered implementation document through
ordinary fields. It does not ask owners to edit JSON. The Python bridge,
website gateway and browser client each use fixed operation and result shapes.
Every route requires the owner session; writes require session-bound CSRF.
Layout PNGs are served from an exact immutable version with bounded bytes,
verified hash and inert image headers. No local path, storage key, runtime
reference, file hash or provider payload reaches the browser.

A saved version is reconciled from exact readback, even if another device has
already published a newer head. A failed or uncertain readback leaves the
draft intact and blocks repeat Save until Refresh. Create/Edit cannot replace
a staged draft silently. Result history is selection-only; retired history
pages through all 256 possible versions in bounded groups of 50. Explicit
downloads produce a PNG layout, a Markdown product/source document and a
Markdown implementation order from saved validated content. Saving does not
start an Agent, accept a generated result or buy a product.

Two independent reviews are clean after correcting a draft-overwrite action,
an accepted-save/readback failure, 50-item history truncation, and a
two-device race where a newer version became the head first. A source guard
also verifies every new route uses the shared owner gateway; the new Project
panel has a distinct React key and remains in the compact keyboard order.
The final checks pass: 82 Python bridge/storage tests, 434 web tests,
TypeScript, ESLint and production build, plus built desktop/mobile garage
workflows against disposable Python/SQLite. The built workflow saves all
three result types and loads the exact layout PNG without overflow. The
rebuilt wheel/source archive pass exact artifact verification, and an isolated
wheel import resolves the fixed deliverable bridge. Live Agent promotion,
owner acceptance and the actual owner's garage/floorplan remain separate
gates. The Windows-normalized staged secret diagnostic reports no candidates;
cross-platform CI remains a separate gate.
