# Preserve bounded browser evidence at the original deadline

Base348442e16b7af552eec355e3010b6c96e5c0526a remains preserved on its
original branch, including the failed actual-run report and disposable state.
The actual run timed out at browser readiness and failed the browser-group
absence cleanup proof. Later group absence is diagnostic only.

Two clocks explain the evidence gap: the Python40second deadline begins at
Chrome spawn, while Node's remaining-time clock begins after Node startup and
stdin parsing. The parent can reach its deadline before Node emits final JSON.
This identifies a reporting seam, not the UI predicate that failed.

The helper now emits an initial and changed-only progress record containing the
same eleven booleans plus eight diagnostic-only Project/Task existence,
exact-text, CSS-renderability and viewport-intersection booleans. At most16
progress records consume at most12KiB;4KiB is reserved for the fixed final
record within the parent's16KiB cap. No DOM, IDs, URLs, coordinates, raw errors,
commands, provider values or debugger payloads cross the report boundary.

The parent uses positional reads to avoid moving the child's shared stdout
position. Only complete newline-framed records with exact schemas are accepted.
Timeouts can preserve the last complete typed observation; malformed evidence
cannot replace the authoritative timeout or grant success. A ready progress
record, incomplete tail, duplicate final or late final cannot pass. Success
still requires final typed readiness, helper exit0, all eleven original checks
and an explicit parent monotonic receipt before the original40second deadline.
The original/tasks landing, fixed desktop viewport, browser predicates,
process-control authority and persistent15second cleanup window are unchanged.
No scrolling or offscreen acceptance fallback is added.

Verification:25 Python methods PASS in4.417s with ResourceWarnings as errors,
including seven Node protocol/predicate cases through the existing unittest
wrapper. New cases cover real positional reads, partial framing, missing final,
duplicate final, output cap, invalid diagnostic schema, all-true progress on
timeout, all-true final received late, separate offscreen/renderable predicates
and bounded changed-only progress with final space reserved. Compilation, Node
syntax and diff checks passed. Log:
/private/tmp/mentat-acceptance-cdp-progress-tests.log.

No app/Chrome launch, product source change, cleanup semantic change, rerun or
acceptance success is claimed. Independent source reviews remain required.
