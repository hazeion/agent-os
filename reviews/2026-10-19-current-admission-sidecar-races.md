# Current admission sidecar races

The frozen `13a3e545` full inventory exposed unchanged simultaneous-context
Send and Agent capacity tests failing during concurrent current-database reads.
The original assertions, thread barriers, deadlines and adapter behavior remain
unchanged.

An instrumented repetition of the original Send test captured an actual
`FileNotFoundError` opening the WAL after its inode had been validated. Closing
the last owned SQLite connection can checkpoint and remove that WAL outside the
database-open barrier. The generic admission error bypassed the existing three
attempts. After addressing that disappearance, repetition captured a second
case: opening a new regular WAL inode after validation of the previous inode.

An actual owned SQLite probe also demonstrates a descriptor opened just before
the last connection closes: its link count changes from one to zero while its
inode remains fixed. Such removed descriptors must be recaptured too.

Only missing WAL opens, removed regular WAL descriptors and safe regular WAL identity turnover now use the
existing transient-sidecar classification. Unsafe type, link count, size,
permissions, primary identity, schema and captured-prefix failures retain their
refusal checks. Each attempt starts admission again; no bytes from one attempted
capture are reused in another.

Independent review found two descriptor gaps in the prior capture: same-inode
permission changes could escape the earlier path checks, and replacement by a
FIFO could block before descriptor validation. WAL opening now uses fixed
`O_NONBLOCK` with `O_NOFOLLOW`. Regular type, reparse, owner/0600 on POSIX, link
count and size checks run before classification or reading and after capture.
Hardlinked, public-mode, nonregular and oversized descriptors receive permanent
refusal. Deterministic tests cover chmod before/during reading, a hardlink added
during reading, an unsafe replacement and an actual FIFO replacement with no
read. The safe replacement fixture explicitly has mode 0600.

Public read-only admission uses the same existing three attempts and 0.01-second
pause as writable admission. Writable admission still calls the single-attempt
private helper, so budgets are not multiplied. Read-only contexts never replay
consumer code after yielding. Strict archival capture is unchanged.

Conversation connection setup maps kernel admission refusal into its existing
`ConversationRepositoryUnavailable("conversation.schema_unsupported")` boundary.
The unchanged replaced-trigger test verifies that contract.

Deterministic coverage closes the actual last owned SQLite connection between
WAL validation and opening, through all three entrypoints. It checks preserved
current rows and primary inode. Other cases cover exact attempt exhaustion,
unchanged source, safe WAL replacement versus a hardlinked WAL, immediate
permanent refusal and no consumer replay. The first 32 focused kernel and typed
Conversation methods passed; the two additional classification tests also
passed, all with ResourceWarnings treated as errors. Logs:

- `/private/tmp/mentat-current-admission-fix-kernel.log`
- `/private/tmp/mentat-current-admission-fix-extra.log`

The frozen Agent capacity test reproduced its barrier failure on its first
attempt: the peer's missing-WAL failure prevented reaching the barrier. A first
fixed repetition reached 30 passes before exposing the removed-descriptor case.
A loaded Send repetition reached 22 passes then hit its unchanged worker-join
deadline without a binding error; that result remains a failure. A subsequent
40 unchanged Send repetitions passed before the final descriptor safeguards.
No assertion, deadline or adapter behavior was changed to obtain these results.

The final source passed all 37 kernel and unchanged typed Conversation methods
in 10.076 seconds, plus both unchanged concurrency targets in 3.043 seconds,
without skips or ResourceWarnings:

- `/private/tmp/mentat-current-admission-fix-final.log`
- `/private/tmp/mentat-current-admission-fix-exact-concurrency.log`

Extended repetitions finished with 40/40 passes for each unchanged concurrency
target. Those processes started before the final `O_NONBLOCK` addition, so their
logs are supporting functional evidence rather than an exact-final-head gate:

- `/private/tmp/mentat-current-capacity-race-final.log`
- `/private/tmp/mentat-current-context-send-race-qualified.log`

The 37 focused methods and two unchanged concurrency targets above ran with all
final safeguards, including `O_NONBLOCK`. Final exact-commit reviews are pending. These
focused results do not qualify a rebuilt artifact or the full integrated suite.
