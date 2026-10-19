# Runtime dependency qualification comparison

Status: fixed reconstructed comparison implemented and audited. Staging and
production qualification remain blocked; no provider or account use occurred.

## Contract recorded before implementation

The initial contract preserved the baseline public origin lock and official
Hermes source, pyproject and uv.lock. It proposed a separate exact seven-package
qualification candidate, bounded offline artifact/metadata validation, fresh
Linux staging, complete audit inventory and positive/refusal tests. The live
[approved Project work](https://github.com/hazeion/agent-os/issues/239) and
[delivery map](https://github.com/hazeion/agent-os/issues/234) authorize seven
replacements but do not enumerate them. The owner subsequently delegated
reconstructing ordinary dependency choices rather than finding an old artifact.

The current actual audit differs from that historical summary: 111 packages,
34 advisory entries across ten package names, compared with the earlier 27
entries/seven names. The historical names could not be recovered, so this is
not represented as the original seven. Ten affected replacements also require
two companion upgrades to satisfy declared wheel metadata.

## Exact fixed comparison

The separate [candidate document](../deploy/project-runtime-dependency-candidate.json)
records exact filenames, versions, HTTPS PyPI artifact URLs, SHA256 and sizes.
The loader binds its complete byte digest and original baseline digest; source,
Python, uv.lock and all other 99 wheel selections remain unchanged. Metadata
was fetched from each exact primary PyPI release endpoint, then all 112 public
source/wheel artifacts were downloaded into disposable storage and their sizes
and SHA256 values verified before parsing. No candidate package was installed,
imported or executed.

| Package | Baseline | Comparison | Selection reason |
| --- | --- | --- | --- |
| aiohttp | 3.14.3 | 3.14.4 | Current advisory fix floor |
| anyio | 4.12.1 | 4.14.2 | Current advisory fix floor |
| httpcore2 | 2.7.0 | 2.12.0 | httpx2 requires exactly 2.12.0; advisory floor alone was 2.10.0 |
| httpx2 | 2.7.0 | 2.12.0 | Minimum covering all listed fix floors |
| mcp | 2.0.0 | 2.2.0 | Same-major fix floor; avoids unqualified downgrade to 1.30.0 |
| multidict | 6.7.1 | 6.9.1 | Current advisory fix floor |
| oauthlib | 3.3.1 | 4.0.0 | Only listed fixed release family; major-change runtime qualification pending |
| pip | 26.1.2 | 26.2 | Published METADATA version of the listed 26.2/26.2.0 fix |
| pyjwt | 2.13.0 | 2.15.0 | Listed fix floors plus exact primary-source resolution of stale advisory metadata |
| urllib3 | 2.7.0 | 2.8.0 | Current advisory fix floor |
| yarl | 1.22.0 | 1.25.1 | Minimum required by aiohttp 3.14.4; not an affected baseline package |
| mcp-types | 2.0.0 | 2.2.0 | Exact peer required by mcp 2.2.0; not an affected baseline package |

The unchanged source requires `PyJWT[crypto]==2.13.0`. The final twelve-change
graph has exactly that one declared requirement conflict. It is reported and
refused before stage materialization. No constraint, source file or lock entry
was edited or waived.

The initial review retained `PYSEC-2026-4146` as unresolved because its formal
record lists no fixed release and still has an unreleased-fix triage note.
Independent primary-source research subsequently established the exact candidate
fix rather than waiving that advisory. The
[upstream fix](https://github.com/jpadilla/pyjwt/commit/0c87c8c8b1a74cac99ad8115f3050efcb7fbed35)
copies caller options before defaults and includes reuse regressions. It is an
[ancestor of release 2.15.0](https://github.com/jpadilla/pyjwt/compare/0c87c8c8b1a74cac99ad8115f3050efcb7fbed35...2.15.0).
The exact pinned wheel's `jwt/api_jwt.py` equals the immutable
[release source](https://github.com/jpadilla/pyjwt/blob/1d41a6478e1562e68ff667fcd703356acf085f68/jwt/api_jwt.py#L69)
Git blob `a63191df0683f86cd946399a4461884b248a5b1c`. The inspector requires the
exact version, wheel SHA256 and member Git identity before reporting that
candidate-specific review. Changed wheels, versions or source members fail.
Formal advisory metadata is stale; a scanner's zero count alone was not accepted
as resolution. The unchanged Hermes 2.13.0 source requirement remains blocked.

## Implemented interface and tests

`python -m mentat.project_runtime_dependencies --artifacts ABSOLUTE_DIRECTORY`
inspects verified source/wheels without execution. Fixed CPython 3.13.14/Linux
x86_64 requirements and activated dependency extras are checked. With `--stage`,
only a fresh Linux destination is eligible, and any requirement conflict or
unresolved advisory refuses before extraction. The baseline origin command
still selects only its original lock; the shared private extractor preserves
its descriptor-relative artifact, path, symlink, aggregate and identity checks.

`--audit` runs pinned pip-audit 2.10.1 in this disposable tool environment using
isolated Python, exact hash-bearing requirements, strict collection, no pip or
dependency resolution, PyPI service and a fresh owned home/cache. No proxy,
netrc, provider credential or owner configuration is inherited. The worker has
a 300-second absolute budget, four-MiB stdout ceiling and owned-child cleanup.
Complete exact coordinates and zero reported findings are required. The output
records local scanner execution, specific advisory reviews, any unresolved
advisories and `production_qualified=false`.
`--audit-report` can check supplied JSON but explicitly cannot verify execution.
Neither interface issues a trusted readiness receipt or production capability.

Final local Python 3.13 validation on macOS: 35 combined dependency/origin methods,
31 pass and four existing Linux-only origin methods skip. New tests exercise
positive synthetic seven-replacement POSIX staging, exact unchanged upstream
bytes, fixed twelve-change manifest, existing destination refusal, metadata and
source conflicts, extras, unresolved advisory refusal, strict audit inventory,
actual owned inert audit-child success/timeout/output/exit cleanup, and isolated
environment. Synthetic stage tests control the platform flag and execute no
staged code; they do not claim actual Linux qualification. One sandboxed run
could not signal its owned test group; the final host run verifies cleanup.

Independent review found that the initial audit cleanup incorrectly treated a
terminal leader as sufficient closure. A descendant could hold stdout after
leader exit or outlive successful report parsing. The correction observes the
exact spawned leader with non-reaping WNOWAIT, preserving its PID until the
original new-session group is signaled. It then reaps that leader and requires
observed group absence within a separate bounded cleanup interval. No signal
is sent after reaping; later numeric-group probes are read-only. Permission
denial is never absence evidence. Unverified closure refuses success and keeps
the owned public temporary root; verified closure precedes root removal and
the final unchanged audit-deadline check. New finite inert descendant cases
cover both inherited and closed stdout, plus a false-closure result proving
that a successful report cannot bypass retention. No discovered PID is used
for control. Earlier intermediate cleanup tests failed on terminal-Darwin
leader queries; those failures are not passing evidence.

The ordinary fixed-comparison `--audit` command completes against all 111
packages with zero reported findings and the exact reviewed advisory evidence.
The original 111-package baseline scan refuses vulnerabilities. A separate
single-package baseline probe verified the real worker's positive path before
the comparison was available. Source parsing and whitespace checks pass.

Reproduce the public advisory scan from the source checkout with a dedicated
disposable tool environment, without installing any candidate wheel:

```sh
python3 -m venv /absolute/disposable/audit-tools
/absolute/disposable/audit-tools/bin/python -m pip install packaging==26.2 pip-audit==2.10.1
/absolute/disposable/audit-tools/bin/python -B -m mentat.project_runtime_dependencies --audit
```

The October 19 observed result binds candidate SHA256
`7dfea05f8a5f10060ffc548877ff2f3795654e1a2730beb3b3bfc916205950f6` and
audit-report SHA256
`b0b18d8e091340e132caaa4310125b4cdf2b5ab2154d6c12771470f164966b4d`.
It reports 111 packages, zero findings, verified local scanner execution and
candidate-specific reviewed `PYSEC-2026-4146`, with production qualification false. These are
observed report identities, not permanent safety or readiness receipts.
For metadata inspection, supply `--artifacts /absolute/disposable/public-artifacts`
containing the baseline source archive, 99 unchanged baseline wheels and twelve
manifest wheels. Artifact sizes and hashes must match; inspection reports the
unchanged PyJWT pin conflict. No actual candidate stage has been built.

## Official upstream option and remaining gates

The latest official release inspected is
[v0.22.2](https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.2),
published October 15, 2026, at immutable commit
[d923a5e](https://github.com/NousResearch/hermes-agent/tree/d923a5eb487a17c0a68801bba9ef0f56c81040a8).
Its exact pyproject Git blob is `5145f275d14a0ab119802821c715a33123b15551`.
It still pins PyJWT 2.13.0 for Python >=3.14. Its own comments state only Python
3.14 is supported; older-Python metadata exists for updating older installations.
Treating those dependency markers as permission to run a dependency-free 3.13
engine would evade the contract. The release was inspected only, never installed
or substituted for the baseline. No verified official-release path removes the
hard pin; upstream fix/release and a newly reviewed source qualification remain
options, rather than an automatic fallback or a maintained fork.

The actual twelve-change scope and source constraint conflict must be resolved
before real staging. Then actual isolated Linux unchanged-stock
Hermes/PIL/image/broker and loader/helper qualification remain required. Candidate
JSON packaging inventory also needs a coordinated change outside this lane:
current package-data rules include only the baseline origin lock. Request-policy
implementation approval, account consent, live provider/model qualification,
canonical admission and garage acceptance remain separate. Two independent
reviews precede publication. No push, PR, provider factory, credential read or
production execution is part of this checkpoint.

## Current-storage publication preparation

The updated local dependency branch normally merges pure current-storage
cleanup302468c, preserving the original dependency feature history. Its runtime
modules, fixed candidate manifest and test bytes remain identical to frozen
QA1c33. The18 previously reviewed public candidate fingerprints from packaging
31188a8 now belong to this dependency branch: all217 pure-cleanup baseline
entries and non-results metadata remain exact, yielding235 entries. No detector,
threshold or exclusion changes were made. The packaging resource inventory
remains a separate dependent change; this branch does not claim an installed
candidate resource is available before that packaging change. Gates are deferred
while the second complete integration run uses frozen1c33. No publication or
release-readiness claim is made by this local history preparation.
