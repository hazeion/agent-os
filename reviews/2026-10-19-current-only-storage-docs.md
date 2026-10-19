# Current-only storage documentation

Contract recorded before editing: reconcile current contributor, architecture,
data-layout and roadmap guidance with the owner’s explicit fresh/current-only
decision. Preserve current authority, recovery, privacy, unknown-outcome and
retention rules. Historical completed work remains history, with supersession
made explicit. SQLite46, backup format 5 and restore protocol 4 are the supported
storage boundary. No platform default or runtime capability is changed here.

Retire obsolete deleted-module documentation assertions, retain useful inventory
and privacy checks, and add no replacement source-string mirror tests. ADR0002
records the tradeoff; ADR0001 retains its original decision with a supersession
notice for old storage compatibility. Focused checks and independent reviews
will be recorded after editing.

## Changes and verification

Current contributor and architecture guidance now specifies SQLite schema46,
backup format5 and restore protocol4 only. Current valid row formats, authority
receipts, unknown outcomes, capacity, privacy and recovery remain documented.
The data-layout contract retains seed/directory/config/browser/external inventory
and exact current backup, pinned-file, read-only admission and Task export
boundaries. The README adds a short current-storage note and links the focused
guide. No runtime, configdefault, application file or secret baseline changes.
The explicit repository `data_dir = "data"` development override is unchanged.

ADR0002 records the owner’s decision and consequences. ADR0001 is preserved
with a limited supersession notice covering only retired storage provisions.
ROAD_TO_BETA records the old milestone sequence as history and makes current
integrated QA an open gate. The actual active roadmap is IMPLEMENTATION_PLAN.md
in this tree; no MENTAT_PIVOT_IMPLEMENTATION_PLAN.md exists or was fabricated.
The reviewed provider-choice commit9434e63779cec69f6a847e4a7277703bcaafe653 was
normally merged: OAuth selection is recorded, while policy implementation,
account consent and exact live qualification remain explicitly pending.

The existing data-layout contract module now has seven retained methods. Its
deleted data_migration.py read and old upgrade/CLI source-mirror assertions are
removed. Current seed/target inventory, privacy/external state, platform override
precedence, read-only/missing-only publication, backup consistency and primary
document links remain checked. No new source/config-string mirror tests were
added. All seven methods pass with ResourceWarnings treated as errors in0.011s:

```sh
/private/tmp/mentat-ci-recovery-venv/bin/python -W error::ResourceWarning -m unittest tests.test_data_layout_contract -v
```

All local Markdown targets in the eight edited guide/ADR files resolve. A
focused stale-contract scan found no live promise of old archive acceptance,
standalone Agent convergence, old migration commands or schema5 export. Remaining
format1/2 plan rows and row-level legacy provenance describe valid current data.
No hosted CI, full integration suite or release readiness is claimed here.

Independent review found two residual compatible-export exclusion clauses and
an ambiguous incomplete-reservation sentence. The obsolete clauses are removed.
The archive boundary now explicitly distinguishes unsupported/malformed states
from exact recognized current protocol4 interruption recovery, which remains
supported. These are documentation corrections only.
