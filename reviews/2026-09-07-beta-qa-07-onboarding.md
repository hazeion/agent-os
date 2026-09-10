# Beta QA batch 7 — Agent onboarding

Owner-approved September 7, 2026. Base: `0640b0b` (locally verified batch 6).

## Scope and verification

- [Default Agents workspace has no UI path to create an Agent](https://github.com/hazeion/agent-os/issues/212): an explicit setup entry point,
  supported local Hermes discovery, name-only preview and confirmation, canonical
  registry creation, and actionable Codex/Vercel setup guidance.
- Preserve the unique runtime identity binding. This slice reuses the configured
  local Hermes default identity; it does not create profiles, duplicate Codex's
  fixed identity, grant files/task-creation capabilities, or start work.
- Check and preview remain read-only. Confirmation binds the exact configuration
  and registry state, uses existing locks and atomic creation, and verifies the
  resulting canonical record. Ambiguous replies require Check before retry.
- Validate exact browser/Node/Python projections, concurrency and stale previews,
  capability restrictions, lazy setup loading, production UI, package inventory,
  and two independent read-only reviews. Positive Hermes tests use controlled
  capability fixtures because this host has no available Hermes CLI.

## Evidence

- Implementation integrated as `aa0f47b`. Author checks passed: all 351 web
  tests with lint/typecheck; 96 Python setup/registry/bridge tests (one skip).
- Both independent reviewers found no actionable issues. Each independently
  passed ten Python setup tests and five web setup tests. Review B explicitly
  applied the owner's requested review-agent skill.
- Integrated lint/typecheck, all 351 web tests, and production build passed.
  The first build encountered a Windows lock from the running QA server; the
  clean rebuild passed after stopping that owned server.
- Production Agents initially includes only the existing shell script. Explicit
  Create Agent / Setup opens the lazy panel. Check correctly reports unavailable
  Hermes, retains the single Direct Agent, and exposes supported Codex and Vercel
  instructions. Close returns keyboard focus to the opener. Reopen/recheck works.
  Desktop and 390px mobile layouts were inspected; mobile has no page overflow.
- Canonical creation, changed previews, concurrent confirmation, remote mode,
  registry ceiling, hostile projections, and ambiguous-reply recovery are covered
  by controlled fixtures and real SQLite/private HTTP tests. This is not a claim
  of successful execution on an actual configured Hermes installation.
- Batch 7 is locally verified. Final cross-batch audit is recorded separately.
- Publication and cross-platform CI remain pending.
