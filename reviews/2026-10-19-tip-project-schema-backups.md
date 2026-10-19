# Producer-tip historical Project backups

Base: PR 321, `dcb0e22`, schema 46. The existing private-unit contract lists
historical schemas 38 through 42, but provider, registry, Task, Project,
Conversation and Run validators omit those versions. The initial three-method
regression run reports five errors, one for each historical version, at the
provider check. Its future-version and malformed-schema refusals pass.

Add only literal versions 38 through 42 to those six existing allowlists.
Preserve their other historical versions, current schema 46, exact fingerprints,
authority receipts, row checks and relationship validation. No schema migration,
runtime capability, provider connection or production admission changes.

All four final backup methods pass. They cover complete normalized empty units
for all five versions; one synthetic Hermes Agent and configuration per version,
with complete rows compared before and after filtering; retained schema versions;
unchanged bytes during validation; and rejection of a future version or modified
DDL after first proving the baseline unit valid. Agent capabilities are empty and
no runtime, model or account is contacted. This proves the stated registry case,
not arbitrary populated Task/Run/blob backups or whole-journey acceptance.

All six historical policy-migration methods also pass. Both independent source
reviews are clear. Review identified that the initial populated fixture compared
only selected fields; the final fixture compares complete Agent/config rows.
The final four-method run passes in 11.649 seconds with no skips.

Hosted current-head verification and dependency integration remain required.
No PR merge, full Python-suite pass or production activation is claimed.
