# Bounded Project proposal artifact parser

Scope: parse one at-most-32-KiB UTF-8 JSON artifact into inert owner-review
suggestions. This is a pure validation component for the later registered
`project_proposal` Run intake, not a browser submission, Task mutation, Agent
assignment, plan publication or Run admission capability. The caller must
first establish registered artifact and exact successful source Run evidence;
model prose or a generic Console attachment is never a source.

Version 1 has exact top-level keys `version`, `summary`, `questions`, and
`tasks`. It permits up to eight bounded clarification questions and 16 new
Task suggestions. A Task has exact `title`, `description`, `agent_id`,
`due_date`, and `after` fields. A question has exactly `kind` (`measurement` or
`clarification`) and single-line `text`; every question blocks Apply.
`agent_id` and `due_date` may be null; `after`
contains distinct earlier zero-based suggestion indexes only. No Project,
Task, Run, path, tool, credential, purchase, external-message or operation
field is accepted. Existing Task edits require a separately reviewed exact
operation format and are absent from version 1. Blocking questions make the
proposal ineligible for automatic Apply; owner response and revision routing
are separate Inbox capabilities.

Reject invalid UTF-8, duplicate JSON keys, nonfinite numbers, unknown or
missing keys, malformed dates, unsafe control characters, overlong text,
duplicate titles/questions, cycles/future/self dependencies, and over-capacity
raw or NFC-normalized canonical input before producing a
snapshot. Text remains inert and cannot grant tools. The parser returns only
normalized safe text, optional syntactically valid canonical Agent IDs and
earlier-row references; existence/current-grant checks belong to exact intake
and Apply. A canonical snapshot digest supports immutable registered-output
binding but is not independent source provenance.

Tests: maximal boundary, multibyte byte count, duplicate keys, unknown
authority fields, invalid assignment/date, dependency ordering/duplicates,
question-only clarification, malformed JSON, nonfinite values, Unicode
normalization expansion/line separators, stable canonical digest, and wheel/
sdist inclusion. Obtain two independent read-only code reviews and fix
findings before a full PR.

Verification: all 11 focused tests pass. Independent reviews found and cleared
canonical NFC expansion, Unicode line-separator and package-inventory gaps.
Both re-reviews report no remaining findings. The real wheel and source archive
pass exact-content verification, and an isolated wheel installation imports
both proposal modules, validates the schema-42 private graph and parses/digests
a question-only proposal. The website runtime reused for packaging came from
an existing build after verifying identical tracked `web/` source.
