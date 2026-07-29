# Beta evidence: bounded Hermes Runs inline-image contract

Status: upstream draft published; Mentat remains fail-closed.

## Why this exists

Mentat's remote Agent Console must preserve the existing Runs lifecycle:
submission, pollable status, SSE events, approval handling, and stopping.
Chat and Responses already accept image content, but neither is a substitute
for that controllable lifecycle. Mentat must never transmit an attachment's
local path, filename, storage key, hash, or an arbitrary remote URL.

## Required upstream contract

- `GET /v1/capabilities` advertises `run_inline_images`, version `1`, its
  data-URL-only transport, bounded image count/bytes, and fixed `POST /v1/runs`
  path.
- `POST /v1/runs` accepts the existing plain-text input unchanged, plus a
  compact OpenAI content-part input containing `input_text` and `input_image`.
- An image must be a syntactically valid `data:image/...;base64` value for PNG,
  JPEG, GIF, or WebP. The draft limits a request to four images and each image
  to 5 MiB after base64 decoding.
- HTTP(S) URLs, file uploads, local paths, unsupported image types, malformed
  data, excess image count, and oversize input are rejected before Hermes
  allocates a run, stream, status record, or server-side agent.
- An accepted image input uses the unchanged Runs status, SSE event, approval,
  and stop controls. The server does not expose submitted image bytes through
  status or events.

## Verification and release gate

Mentat may recognize this capability only after it is merged upstream,
released in an official Hermes build, advertised by the installed runtime, and
verified again through Mentat's authenticated transport. Until then remote
inline images remain unavailable and general file/artifact transfer continues
to degrade clearly.

The future Mentat adapter must still transmit only bytes from its validated,
run-scoped attachment snapshots, use the exact advertised limits, never send a
path or URL, bind the image selection to the current run/connection, and use
the existing post-submission status and stop verification.

## Upstream implementation evidence

- Draft upstream pull request:
  [NousResearch/hermes-agent#68202](https://github.com/NousResearch/hermes-agent/pull/68202)
- Fork branch: `hazeion:feat/http-runs-inline-images` at
  `9f8964e03d4965dc3585ff70b5b90e7ef4abe945`, based on upstream `main`
  `67e73ae95899c57b9b9134b4b10a2520dffd0a16`.
- The Milestone 2-wide adversarial pass found and fixed an inherited free-form
  image-detail field. Runs now accepts only the fixed `low`, `high`, or `auto`
  values, with a regression proving unrestricted text is rejected before run
  allocation.
- Focused Runs, session-image, and API-server suite after that fix: 257 tests
  passed.
- Ruff, Python compilation, and whitespace checks passed.
- The isolated Hermes worktree had no installed `website/node_modules`, so the
  Docusaurus build was not run locally. The draft remains subject to upstream
  review and CI.

This is evidence of a proposed upstream capability, not a declaration that
remote image transfer is available. Mentat must require an official released
runtime that advertises this exact capability and independently verify it over
the authenticated transport before enabling any remote image operation.
