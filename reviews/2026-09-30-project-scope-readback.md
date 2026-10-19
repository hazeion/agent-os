# Private scope readback after restart

Status: implementation contract within the
[approved controller](2026-09-29-official-hermes-project-controller.md).
This is observational only. It does not enable restart execution, acquire a
launch token, signal a process or settle a Run/provider outcome.

Both independent contract reviews are clear. The private fixed worker now
implements source-preserving exact-reference snapshots and independent bounded
kernel observation. Code reviews identified and corrected late post-cleanup
evidence, contradictory IPC state/reason pairs and missing canonical source
authority validation. Both final code reviews are clear. The final actual Linux
readback/scope/journal group passes all 70 tests with no skips; all 17 new
readback tests pass, including source-damage and closure-witness rejection.
Five portable reply/deadline regressions pass on Windows. Wheel/sdist inventory
and integrity checks pass; ten exact source/wheel/sdist/installed members match,
with three isolated installed imports and the fixed worker command verified.
No callable product capability or complete recovery
proof is claimed.

## Boundary

Read one exact schema-44 scope record by canonical Run ID, generation and
revision from the private validated database under the server-owned data root.
Each snapshot requires the exact schema-44 signature and validated canonical
Run authority receipt, which is also pinned in pre/post reference comparison.
The caller supplies no unit,
UID, cgroup path, PID, command or environment. Reject an uncommitted caller
transaction. Load the complete generation/scope graph in a coherent read
snapshot, release it before bounded kernel operations, then revalidate the
same immutable receipt/revision in a new snapshot before returning evidence.
A changed receipt yields unknown, never evidence for the prior selection.
Both snapshots must also match the pinned private root/database identity and
current approval epoch. Use the established source-preserving read-snapshot
boundary, including WAL handling, rather than an arbitrary old connection.
Replacement, restore or epoch change yields unknown; a historical match after
restore cannot be described as current Mentat-owned work. Scratch copies are
disposable and private; source database/sidecars/configuration remain unchanged.

Evidence has a fixed ten-second absolute acceptance deadline, covering process
startup, both database snapshots, kernel operations and verified worker cleanup.
Once process creation exposes the owned child, a parent timer bounds its work,
including blocked input writes. Run the fixed inspection worker with
credential-free environment and bounded resources; terminate/reap its owned
process tree on timeout, with no automatic retry. OS process creation and
unverified OS cleanup cannot promise a bounded return time: retain unresolved
ownership, and never return a matching sample after the acceptance deadline.
Each systemd read has at most two seconds or the remaining wall budget,
whichever is smaller; reply/control/boot/PID fields have fixed byte ceilings
(8 KiB systemd stdout/stderr, 4 KiB control/PID, 64 bytes boot UUID), and the
single normalized worker result is at most 4 KiB. Remaining-time checks apply
to traversal and post-validation too. Expiry produces unknown without a late
sample or cached evidence. No worker receives provider credentials or token
values; fixed input is the trusted root plus the exact canonical reference.

Only fixed Linux operations may observe a complete retained kernel identity.
Require the current boot UUID and operator UID to match the receipt, derive
the single fixed cgroup hierarchy from UID/unit, open it descriptor-relative
without following symlinks, require cgroup2 and exact device/inode equality,
require cgroup inode ownership to match retained/current UID, and compare bounded
systemd ActiveState/ControlGroup/InvocationID readback
before and after the observation. Check the retained launcher PID/start ticks
when claiming that launcher still exists; PID absence/reuse does not prove
scope termination. Never look up another unit or reconstruct ownership from
a name alone. A scope can remain populated after its original launcher exits.
Parse only unique expected ASCII fields: duplicates, extra fields, unsupported
states, invalid values and oversized data fail closed. Do not reuse the held
scope helper's removed-directory fallback; it relies on original handles that
the independent observer does not possess.

Return a small private observation: matching populated, matching empty,
unknown or conflict, with a fixed reason code. A matching-empty observation
requires the exact reopened cgroup inode and generation to be observed empty.
An absent path, unavailable control file, malformed/oversized reply, permission
failure, new boot/UID or changed invocation remains unknown/conflict. Missing
in-memory state and an inactive/not-found unit alone cannot prove emptiness.
Unknown/starting records without complete retained identity produce no lookup.
Prepared/cancelled records are intent/history only, not a live scope.
Terminal stopped metadata plus a newly matching populated kernel scope is
conflict/unknown, never a new active work claim. Samples are timestamped;
matching empty/populated describes only that descriptor-bound observation,
not durable closure or guaranteed freshness after return.

No observation is a ScopeWitness closure token. It cannot change journal state,
release shared capacity, refund spending, retry, resume, start, stop or register
outputs. Lost original tokens remain lost. Authenticated recovery actions and
the complete production admission/backup graph remain separately reviewed gates.
No browser, bridge, service or CLI command is added in this slice; private
kernel references stay out of ordinary projections and raw errors are omitted.

## Verification

Test exact-reference selection, uncommitted/stale/revision/generation refusal,
all state/identity branches, changed receipt during readback, boot/UID mismatch,
PID reuse versus populated descendants, fixed unit/environment/command bounds,
no-follow traversal, wrong filesystem/inode/invocation, missing/slow/oversized
control data and no database/file mutation. Use actual fixed inert scopes on
Linux for populated readback and the real cleanup case, retaining the original
owner handles until cleanup; a newly opened observer must not inherit them.
If systemd removes the path before an empty scope can be reopened, that fixture
must honestly produce unknown. Test a reopenable empty window only if the
supported host demonstrates it; never weaken identity to force matching empty.
Provider and owner services remain unused. Obtain two independent contract and
code reviews, correct findings, run proportional checks and publish a full PR.
