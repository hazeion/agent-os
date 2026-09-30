# Schema 44 current-test inventory synchronization

Exact base: PR 313 at 1aa741b724484a963b0767dbfe047ad25d834ef0.

Nine current-schema assertions still expected 43 after the scope-journal migration advanced production to 44. One schema-16 final migration readback also expected 43. This patch updates only those current expectations and adds the actual worker-generation, call and scope tables to the existing Run inventory subset, matching the correction reviewed in PR 316. Historical schema-43 fixtures, schema-signature checks, foreign-key checks, refusal gates and backup assertions remain unchanged.

No production, authority, migration, workflow or watchdog code changes. Older schema-41/42/43 branches must retain their own expectations. The nine directly affected methods passed on Windows in 7.656 seconds. Full related migration classes, actual Linux qualification and two independent reviews remain publication gates.

Publication evidence: the nine directly affected methods pass on Windows (7.656 seconds) and actual Linux (2.846 seconds). All 14 methods in the four related migration modules pass on Windows (9.929 seconds) and Linux (2.626 seconds), including exact-source drift refusal, transaction refusal, foreign-key/signature checks and private backup rejection. Both independent source reviews are clear. These are local fixture results; current-head hosted acceptance remains pending.
