# PR 291 expected-Agent signature compatibility

Exact base: 22498e40f4bd5f14120b6c38115b8a1aea89e188 (schema 42).
Completed Windows group 3 job 109779632998 / run 36680600885 exhausted the
existing 2400-second budget. Its retained-schema-12 backup/restore method
passed in 1044.771 seconds before the group later exhausted its remaining time.

AgentRegistry and original registry-test preimages exactly match reviewed
PR 290/294. The private Console production/test blobs exactly match qualified
PR 294. This carry adds only the same immutable max-eight, full-recipe expected
signature cache and eight boundary tests. Actual schema, rows, receipts,
relationships and capabilities remain fresh. No source-42 gate, timeout,
matrix or assertion is removed; no schema-43/44 product code is imported.

All 59 actual Linux registry/cache/schema12/plan-policy methods pass in
12.423 seconds; all 15 Windows cache/CI methods pass in 8.529 seconds. Shared
schema-41 timing evidence is historical. Qualified PR 294's identical backup
suite passes all 53 Linux cases in 86.573 seconds. The original schema-41
implementation additionally passes the complete Windows private suite (53
methods, 272.144 seconds, one POSIX skip).

Two independent per-head compatibility reviews and hosted acceptance remain
separate gates. No hosted improvement is claimed. Publication remains held to
preserve the pending exact-head security approval set before selective carry.
