# PR 317 focused dependency and current-schema CI repair

Exact base: c20e427275265e8c95224137a1354a0356cf496b.
This single new PR is outside the paused 60-head dependency publication proposal.

Its four dependency preimages match already reviewed baselines: package files
match PR316, and native/quality locks match PR296. Carry byte-identical reviewed
Next16.3.6 package files and the urllib3 2.8.0 version/two-hash corrections.
No package-key graph, unrelated dependency, toolchain or workflow changes.

Eight inherited current-schema assertions still expect43 while production is44.
Carry the exact reviewed4c053bc fixture result only at those sites (including
schema16 final readback). RunRepository's current44/table assertion is already
fixed in the base and remains untouched. Historical43 fixtures and every source,
foreign-key, backup and refusal assertion remain. No product/helper/provenance,
authority, schema, provider, timeout or matrix implementation changes.

Reference native qualification: strict native/quality audits zero; full native
hash-checked resolution Linux/Windows; Linuxquality hash install; pip-tools7.6
reproduced official PyPI hashes. This is shared local evidence, not hosted proof.
Fresh per-head schema/negative/lock checks, frozen web install/audit/check/build
and two independent combined compatibility reviews are publication gates.

No PR merge, owner service or provider/model call is part of this correction.
The existing60-head proposal remains unchanged and unpublished until approval.

Completed per-head qualification: the manual Python schema/negative/dependency
suite passes 35 executions on Linux (113.488 seconds) and Windows (19.729
seconds), representing 31 distinct methods plus four deliberately repeated
target methods; CI discovery remains unchanged. Frozen npm installation,
fresh audit zero, lint/typecheck and all 512 web tests pass (49.471 seconds);
production build passes. All 63 private bridge/preview methods pass (32.852
seconds). Exact current native and quality strict audits both report no known
vulnerabilities. Both independent combined compatibility reviews are clear.
Hosted checks on the replacement head remain unverified until they complete.
