# POSIX permission fixture correction

Base: PR #273, `faf4d1c0749b10f13bce33edd9e7b7531514f7be`, schema 33.
The previously skipped POSIX fixture expected read-only directory inspection
alone to reject a same-owner 0755 directory, which that existing API does not
promise. Correct only the fixture to use an actual existing private SQLite-file
0644 refusal contract. It warms the cache, creates a real owned temporary
current database, makes only its SQLite file unsafe, requires the established
PrivateConsoleUnitError and asserts byte/time/mode inventory unchanged.
No production permission policy or cache behavior changes. No existing
supported refusal assertion was weakened; the unsupported fixture assumption
is replaced by the actual contract.

All nine cache methods passed on actual supported Linux Python 3.13.14 in 2.512
seconds with zero skips, including the corrected 0644 refusal. Both independent current compatibility reviews A and B are clear. Earlier Windows/profile
measurements remain historical in 2026-09-30-ci-empty-console-template.md; no
new local speed or hosted CI success claim is made. All data roots were owned
disposable fixtures; no model, provider, owner service or configuration was used.
