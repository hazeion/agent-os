# PR 275 schema-34 metadata construction compatibility

Exact base: c7bf5c954c59e064e8f967af40cf58ef03a7f382.
Windows group1 job109892379524 and group2 job109892379539 exhaust their existing
1800-second budgets. Group2's retained-schema10 backup method alone takes610.627
seconds. Profile the exact same local method before adapting the reviewed change.

Only the code-owned expected-Agent signature cache and synthetic memory SQL
constructor change. Preserve this older branch's accepted-version set exactly;
no later schema/model/controller source is imported. The full schema34 migration
recipe and normalizer bind cached immutable SQL tuples. Actual roots, authority,
rows, relationships and capabilities stay fresh and on-disk as before.

Exact local method51.943 seconds before (58 expected file builds39.238 seconds),
11.337 after, with52 full private-unit validations retained. This is local
profiling, not hosted-group success. New regression oracle covers every version
8–34 plus changed recipes/normalizers; key/error/connection/concurrency and warm
actual-schema/receipt refusal remain. Existing1800s guard and matrix unchanged.

Linux56 cache/registry/schema12 methods pass8.237 seconds. Full private backup,
Windows cache/CI and two independent branch-compatibility reviews remain gates.
Historical shared records refer to their original41/42 proofs; this unique note
owns current34 evidence. Publication stays local under the frozen60approvalhold.

Completed remaining local gates: full53 Linux private backup/restore methods
pass70.536 seconds; all23 Windows cache/CI methods pass23.005 seconds. Both
independent branch reviews are clear. Reviewer B independently reran all12
cache/equivalence methods (28.760 seconds). Current34 accepted versions,
original1800s group guard, workflows and all operator-store checks remain.
No remote head changes; hosted acceptance is still unverified.
