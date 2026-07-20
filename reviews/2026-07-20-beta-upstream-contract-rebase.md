# Beta evidence: current Hermes contract draft heads

Status: all Milestone 2 upstream-contract drafts reconciled to current upstream
`main`; Mentat remains fail-closed pending upstream merge and official release.

## Baseline and scope

On 2026-07-20, the six required Hermes API-server contract drafts were checked
against upstream `main` commit
`67e73ae95899c57b9b9134b4b10a2520dffd0a16`. This reconciliation does not
enable any new Mentat remote operation. It ensures the milestone-wide review
will inspect the same current upstream baseline for every proposed capability.

| Required capability | Draft PR | Current fork head | Rebased verification |
| --- | --- | --- | --- |
| Exact approval request binding and safe preview | [#68080](https://github.com/NousResearch/hermes-agent/pull/68080) | `531034a9487034af70c7610711edcf9c8955adf8` | 615 affected API/approval/platform tests passed; Ruff and whitespace checks passed. |
| Exact typed clarification response | [#68105](https://github.com/NousResearch/hermes-agent/pull/68105) | `6c7fdfc4bc84b62e4e3c918e44deea1552ac403b` | 279 affected API/Runs/toolset/clarification tests passed; Ruff, compile, and whitespace checks passed. |
| Exact stoppable continuation | [#68177](https://github.com/NousResearch/hermes-agent/pull/68177) | `0eb64f6bf45a7486bd8a4591d486dd9bf83e1077` | 56 focused Runs/session tests passed; Ruff, compile, and whitespace checks passed. |
| Authenticated complete profile inventory | [#68190](https://github.com/NousResearch/hermes-agent/pull/68190) | `baeb9b2dcb4210ffd33a80fa3908e64e591357ce` | 224 API/multiplex tests passed; Ruff, compile, and whitespace checks passed. |
| Revision-aware Kanban API | [#68200](https://github.com/NousResearch/hermes-agent/pull/68200) | `14491d16851c1b21d9c201dd9fc273d5f9f7d861` | Already rebased to this baseline; 245 Kanban/database and 212 API/multiplex tests passed; Ruff, compile, and whitespace checks passed. |
| Bounded Runs inline images | [#68202](https://github.com/NousResearch/hermes-agent/pull/68202) | `9f8964e03d4965dc3585ff70b5b90e7ef4abe945` | Based on this baseline; the milestone-wide review bounded image detail to `low`/`high`/`auto`; 257 Runs/session-image/API tests passed; Ruff, compile, and whitespace checks passed. |

## Release gate remains unchanged

Each draft is open, mergeable, and still marked draft upstream. Mentat must not
enable approval response, clarification response, continuation, profile
discovery, Kanban mutation, or remote inline images until the corresponding
contract has been merged upstream, shipped in an official Hermes release,
advertised by the installed runtime, and reverified over Mentat's authenticated
transport. A draft branch, a fork build, or a compatible-looking HTTP response
is not sufficient evidence.

The isolated Hermes worktrees did not have website dependencies installed, so
their Docusaurus builds were not rerun during this reconciliation. That
limitation remains visible in each contract's individual evidence record and
does not reduce the release gate.
