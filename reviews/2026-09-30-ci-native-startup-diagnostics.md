# PR #281 native startup observations

The exact PR #281 head `f23cc814106c10e3f1800026c15c9b01a9134d97` failed its
Windows upgrade smoke in run `36075403247`, job `107885484734`. At
2026-09-25 00:34:26 UTC the launcher remained live, both redirected log tails
were empty, and no Node startup log was reported. The entire smoke step lasted
104 seconds including silent baseline and upgrade installation; its timestamps
do not establish exact launcher uptime. The existing preflight report is
buffered under redirection, so empty stdout does not prove preflight never ran.

The failed run retains only its two macOS installers; Windows artifact upload
was skipped after smoke failed. The nearby green PR #279 native run
`36068742489`, head `eca74da84e60f011870cf9198c8d194dd74ed478`, uses identical
native entry, PyInstaller spec, installer, build, lifecycle, CLI, web runtime
and native workflow source. The later PR #299 source has a POSIX-only listener
repair, which does not establish a Windows startup fix. Source-only in-memory
signature measurements at the exact failing head were 0.039335 seconds for
schema 35 and 0.040589 seconds for schema 36; these do not measure frozen
imports, filesystem initialization, authority setup or bridge startup. They
are not evidence of a 98-second signature replay stall. The cause is unproven.

This diagnostic slice changes no startup authority, configuration, schema,
provider operation or readiness deadline. A stdlib-only helper inside the
existing `mentat` package emits fixed phase observations only when the exact
CI flag is `1`, `GITHUB_ACTIONS` is `true`, and the process is frozen Windows.
Each of 25 allowlisted phases emits at most once, with a fixed launcher or
private-bridge role, bounded UTC milliseconds and monotonic elapsed
milliseconds. Flushed stderr makes observations useful even before normal
stdout flushes. No arguments, paths, environment values, credentials, prompts,
provider payloads or owner data are diagnostic fields. Absent GUI stderr and
closed streams are harmless; ordinary launches emit nothing. The first
Python-entry timestamp and the workflow's actual launch UTC timestamp can
distinguish startup before the Python entry point from later imports.

Hooks bracket native verifier/import completion, CLI/lifecycle preflight, data
initialization and listener checks, Node validation, authority preparation,
private-bridge launch/readiness and both Node readiness checks. The existing
15-second internal readiness and 10-second Node-version limits, 30 Windows
health polls, upgrade sentinel/stale-file checks and stop/uninstall assertions
remain exact. Diagnostic hooks do not refresh or override any of those limits.

Independent review identified a concrete privacy gap in the initial archive
implementation: exact seed names and a filename denylist did not constrain
regular files elsewhere in `_internal`. An injected `web/private-notes.json`
or `mentat/session-cache.txt` could have entered the archive. That gap is fixed
before publication.

In Windows CI, the trusted spec seals a relative-path/SHA256 inventory directly
from the completed `COLLECT.toc`, before installer construction or smoke. It
does not discover intended files by scanning the bundle. The mapping follows
the fixed [PyInstaller 6.21.0 COLLECT implementation](https://github.com/pyinstaller/pyinstaller/blob/v6.21.0/PyInstaller/building/api.py#L1088):
executables stay at the bundle root and DATA/BINARY/EXTENSION entries use the
fixed `_internal` contents directory. Unsupported entry kinds fail closed.
The bounded inventory stores no source paths and remains outside the bundle;
ordinary local native builds do not generate it.

Before Windows smoke, the archive script requires exact intended membership
and hashes, plus the existing public data/static inventories. It rejects an
unlisted entry before reading its bytes or descending its directory. Missing
or replaced intended files, links, reparse points, hard-linked files and special
entries fail closed. File hashes are checked again while writing ZIP members;
a change during writing deletes the owned partial output. A fresh fixed ZIP
never replaces an existing output. Failure retention uploads only that validated
frozen ZIP after build/archive success. The original installer upload remains
success-only, and no wildcard installer is newly retained on failure. No
temporary installed app, operator data root, log, private history, inventory
source paths or credential directory is uploaded.

Source-level validation on the exact base and diff:

- All 61 relevant diagnostic/privacy, public archive, packaging, CLI startup,
  gateway and preflight tests pass using the designated Windows Python with
  `-B`. Tests cover gating, flushing, fixed fields and total output bounds,
  GUI/closed streams, refusal of private/linked payloads, adjacent private data
  exclusion, explicit unknown web/package-file injection refusal, missing or changed intended files, rejection of an unlisted file before any byte read, intended COLLECT membership sealing, mutation during ZIP writing, partial archive cleanup and preservation of existing output.
- Behavior tests require phase ordering around the existing mocked operations;
  readiness budgets and workflow upgrade/uninstall assertions remain checked.
- All eleven changed Python sources (including the spec) parse, and `git diff --check` passes.
- An initial broader 72-test selection also encountered the unchanged
  `CliTests.test_connection_status_and_two_step_local_confirmation_are_secret_free`
  fixture returning 2 rather than its expected 0 at local connection confirmation.
  That unrelated connection path was not changed or repaired in this slice.

No compiled archive was downloaded or executed, no native build/installation
was performed, and no CI rerun or cancellation was requested. Actual frozen
reproduction and the hosted diagnostic result remain unverified until an
isolated disposable runner executes the reviewed change. Hold publication for
two independent reviews; do not claim a cause or a passing hosted upgrade yet.
