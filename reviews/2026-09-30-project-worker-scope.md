# Project worker local scope ownership

Implement the owner-approved controller's Linux scope component from the
stock-Hermes qualification prototypes. This is private execution infrastructure,
not a Run-admission API, new browser capability or qualified runtime declaration.
Schema-41 Project dispatch guards remain intact. No model call belongs to this
slice.

Mint one fresh fixed-prefix user scope; keep its environment and limits
immutable. Before handoff, verify the owned launcher generation, scope membership,
systemd invocation, descriptor-pinned kernel cgroup2 inode and finite effective
memory/process/CPU limits. Selected inputs, Agent code and broker capability must
not cross handoff before these checks succeed. The full namespace and fixed
bootstrap are separate components.

The component owns launch of a fixed inert bootstrap; caller-provided Popen
arguments are not command provenance. Before verification it has only a control
socket and can launch no Agent or receive inputs/broker capability. Startup
refusal closes that socket and verifies EOF-driven exit, retaining uncertainty
if cleanup cannot be proved. Its only implemented commands are fixed disposable
qualification actions, guarded by parent scope/deadline readback and a receiver
deadline check. Production Run handoff is not implemented by this slice.

Use the held cgroup descriptor for whole-generation local Stop, including detached
descendants. Never target another named unit or recycled PID to recover uncertainty.
Finished scope removal requires kernel/readback reconciliation rather than POSIX
directory unlink counts. An independent watchdog enforces local termination;
stock CLI flags and configured systemd deadlines alone are not hard-wall evidence.
Only verified local emptiness permits releasing scope handles. Unknown cleanup
must retain caller-owned inputs and canonical Run evidence. This component never
claims an already submitted external provider request stopped.

Tests must cover unlimited/malformed effective limits, unsupported platforms,
unowned/replaced generations, no-follow paths, exact detached-descendant Stop,
finished-cgroup removal, watchdog expiry, and exception cleanup. Run live tests
only against freshly generated disposable scopes; owner services remain untouched.
Obtain two independent reviews and correct findings before a full PR. Durable
controller claims, broker journal/budgets, prepared-input admission, byte pinning,
namespace bootstrap, artifact registration and full hostile qualification remain
required before production execution.

Verification: all 13 tests pass on actual WSL/Linux, including no-follow and
non-kernel filesystem rejection, PIDFD/filesystem/limits/timer-start fault
injection, detached descendant cleanup, removed-cgroup reconciliation, deadline
refusal before control send, and an actual independent parent timer kill while
both fallback deadlines remain ten seconds away. Windows runs four neutral
tests and skips nine Linux-only cases. Initial reviews found unowned startup
windows, mutable launcher provenance, deadline handoff and timer-start cleanup
gaps; the fixed inert factory and fault regressions address them. Both final
independent re-reviews are clear. No owner service or model provider was touched.
Wheel and sdist build and exact-member verification pass. Installing the wheel
in the disposable packaging environment confirms the scope module and its
fixed sibling bootstrap ship together.
