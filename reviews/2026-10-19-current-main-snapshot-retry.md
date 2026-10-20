# Current admission discards an unstable main-file capture

The frozen QA262 full run found a private-lock admission failure while a broker
submission was already waiting: a main database read changed and raised a generic
error. The original broker test and frozen source/evidence remain unchanged.
This branch implements the independently reviewed proposal on pure302; it does
not retry an adapter, submission, consumer action or archival operation.

Current admission retains real root/private/Console and main resources through
its existing three-attempt loop and current-readonly yield lifetime. POSIX opens
use descriptor-relative no-follow/nonblocking resources. Windows uses the existing
no-reparse/no-delete open policy, with checked acquisition unwind and explicit
CRT ownership transfer. The normal unchecked Windows helper callers retain their
existing behavior; the new checked path attempts all owned closes once and refuses
success after uncertainty. Root permissions remain unchanged; only private and
Console require owner700 on POSIX, with main owner600 and one link.

A safely pinned same-inode size/mtime/read-length change discards the capture and
uses the original attempt/pause bounds. Unsafe metadata, replaced or removed
paths/directories, size ceilings and combined quota failures are terminal.
Retained anchors are checked before source discovery so removal during a pause
cannot become fresh initialization. Current-readonly never replays after yield.
Source SQL/SHM is not opened or written by admission. The shared raw file opener
now adds NONBLOCK for safe FIFO refusal; archival content-change errors remain
strict and nonretrying.

Regression source covers a real SQLite checkpoint during the main descriptor
read for all three current entry points, the same checkpoint under strict archival
reading, hostile metadata/directory/identity changes, replacement/removal during
pause, exact exhaustion, combined quota, no after-yield replay, real FIFO swaps,
root permissions, retained-resource close uncertainty and checked Windows partial
acquisition/unwind. A native Windows case exercises no-delete resources; local
POSIX runs cannot qualify that native boundary. No new retry/deadline or source
mutation capability is introduced.

Source checkpoint only: AST syntax and diff checks passed; no tests have run.
Focused execution awaits independent source review and the coordinated quiet
window. No actual app/browser/provider launch is part of this change.
