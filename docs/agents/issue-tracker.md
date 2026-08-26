# Issue tracker: GitHub

Issues and specs for this repository live as GitHub issues. Use the `gh` CLI
for all operations from the `hazeion/agent-os` clone.

## Conventions

- Create an issue with `gh issue create --title "..." --body "..."`.
- Read an issue and its discussion with `gh issue view <number> --comments`.
- List issues with `gh issue list` and request bounded JSON fields when an
  agent needs structured results.
- Comment with `gh issue comment <number> --body "..."`.
- Add or remove labels with `gh issue edit`.
- Close an issue with `gh issue close`.

Infer the repository from the Git remote. Do not copy credentials, private
paths, runtime identifiers, or unredacted local state into issues.

## Pull requests as a triage surface

PRs as a request surface: no.

## When a skill says “publish to the issue tracker”

Create a GitHub issue in `hazeion/agent-os`.

## When a skill says “fetch the relevant ticket”

Run `gh issue view <number> --comments` and include its labels and current
state when those facts affect the workflow.

## Wayfinding operations

Wayfinder stores one map issue with child decision tickets.

- **Map:** one issue labelled `wayfinder:map`, containing Destination, Notes,
  Decisions so far, Not yet specified, and Out of scope.
- **Child ticket:** a GitHub sub-issue of the map. Use a task-list link in the
  map and `Part of #<map>` in the child only when sub-issues are unavailable.
- **Ticket labels:** `wayfinder:research`, `wayfinder:prototype`,
  `wayfinder:grilling`, or `wayfinder:task`.
- **Blocking:** use GitHub native issue dependencies. The dependency API needs
  the blocker's numeric database ID, not its issue number or node ID. Fall back
  to `Blocked by: #<number>` in the child body only when native dependencies
  are unavailable.
- **Frontier:** the map's open, unblocked, unassigned children in map order.
- **Claim:** assign the ticket to the driving developer before doing work.
- **Resolve:** add the answer as a resolution comment, close the ticket, and
  append a one-line linked gist to the map's Decisions-so-far section.

Every map and ticket should be referred to by its linked title in human-facing
text, not by a bare issue number.
