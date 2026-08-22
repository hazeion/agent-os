# Mentat Operations design guide

Status: Superseded

The completed Emerald interface in `public/` is the visual reference for the
Next.js migration. Start with:

- `public/styles.css`, especially the final Emerald foundation layer
- `public/index.html` for the current shell composition
- the running compatibility interface for responsive behavior

Supporting design notes are in:

`design/emerald-operations/DESIGN_SYSTEM.md`

Port the established design into the Next.js app under `web/`. Do not redesign
it or copy the full legacy cascade. The old DOM IDs and view keys are not
contracts for the new routes.

Both interfaces must keep the same product safety rules. They must show honest
loading, empty, disconnected, unsupported, waiting, failed, and read-only
states. They must also preserve exact confirmation text and avoid exposing
credentials, private paths, or runtime identifiers.
