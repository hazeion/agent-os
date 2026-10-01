# PR #276 CI review consistency

Publication base: `d92e1d62c3bc2fe7805a5dd09a30ef979c44013b`. Shared historical review:
`d92e1d62c3bc2fe7805a5dd09a30ef979c44013b:reviews/2026-09-29-ci-efficiency.md`.
The shared record is kept byte-identical across these branches. Its timings
and schema 42 qualification are historical, not measurements of this branch.
Only its location changes: branch-specific evidence below remains separate
so stacked PRs avoid conflicting add/add or independently replaced prefixes.
Source, matrix, security coverage and existing branch deadlines remain intact.

The existing 40-minute runner and fixed matching CI guard remain unchanged.
An explicitly authorized local merge of exact reviewed CI parent `347ffd15d882820c384d11a7bd6e4348af97e049`
resolves the overlapping guard by retaining this branch's original 40-minute
assertion; the parent uses 30 minutes. No deadline increase, dynamic assertion
or test rewrite is introduced. Parent changes and the complete resulting diff
are inspected for expected CI-only dependencies before publication.

The complete merge diff also inherits two already independently reviewed
CI fixtures from this exact parent: both mocked dashboard launches use a
temporary data root, and the profile-identity test uses a fixed interpreter
fixture. Original response, command, PATH/home and exact apply-argument
assertions remain; no owner installation or production files are changed.

## Prior branch-specific qualification

The following preamble is historical and retained from the exact prior head;
its references to earlier reviewed branches and timings remain unchanged.

Original branch-specific qualification remains in the prior commit record cited above.
