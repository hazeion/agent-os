# Signed helper-library historical-origin implementation candidate

Status: local source-review candidate, not published or release/runtime qualified.
Contract history is 52bbc39 → eea55f0 → e6145e6. The parent current host-trust
commit is 78f778951f1abdde146264141e22c74126bd2a43, and the original paused 508
reference is preserved. The reviewed amendment adds only the exact libxxhash0
package and the two exact glibc metadata profiles; no additional pin/tag/layout
has been admitted.

## Interface and source changes

project_library_origin.verify_fixed_helper_library_origins accepts one absolute
private staged-root Path on Linux. Nineteen fixed regular inputs are captured
through retained no-follow/nonblocking descriptors with exact identity, owner,
mode, link-count, size and digest checks. Fixed signed release/index/package
checks precede any selected member/profile handling. Only the fixed gpgv and
dpkg-deb inspection operations receive sealed captured archive bytes. No package
is installed, extracted onto the host, loaded or invoked.

The fixed worker retains the existing resource/command bounds, credential-free
environment, absolute 30-second acceptance budget and verified owned-group
cleanup pattern. Uncertain/late results cannot succeed. The result is immutable,
freely constructible static data, never a witness or readiness state. Its
freshness flag remains false, with explicit security-current, sealed-image,
loader, glibc-rewrite/IFUNC, immutable-helper, FUSE and production-runtime gaps.

project_library_plt selects its profile only for the compiled path/size/SHA256
of the two authenticated libc6 members. It checks the exact 16-byte CET entry tables,
unique executable mappings, one-to-one GOT/RELA relation, distinct JUMP_SLOT and
IRELATIVE rules, bounded hash/symbol/string/version metadata and the structured
ABI compatibility marker. No code is modified or executed. The ordinary global
tag whitelist is unchanged. Its tag/flag checks were factored into one private
helper; the public ordinary ELF parser signature/strict refusal stays intact.

The existing host module now shares only private pure graph checks between the
ordinary wrapper and the fixed library-origin path. Internal immutable parser
records are bound to the exact captured byte size/digest; stale records refuse.
No caller parser callback, allowlist, trust boolean or general override exists.
The ordinary public graph wrapper still parses every regular member with the
ordinary strict parser and rejects unused members. The origin path uses the
same resolver/identity/dependency/alias/edge checks for four reachable subgraphs,
then requires their consumed union to equal the authenticated selected set.
The existing HostClosureCandidate qualification flags are unchanged.

## Verification so far

The short affected portable group ran 48 methods: 47 passed and one actual-Linux
integration method skipped, in 0.320 seconds, with ResourceWarnings as errors:

```sh
python -W error::ResourceWarning -m unittest tests.test_project_library_plt tests.test_project_library_origin tests.test_project_runtime_host_trust tests.test_project_runtime_elf -v
```

The new low-level fixtures exercise metadata validation beyond the outer hash
guard: partial/duplicate/unknown tags, entry size/alignment/overflow, writable or
ambiguous executable mappings, CET/NOP/displacement/GOT mutations, relocation
kinds/counts/addends, IRELATIVE symbol/resolver rules, malformed hash chains and
symbol/string/version bounds, wrong ABI marker/provider, and stale parsed-byte
binding. Ordinary parser/public graph refusal remains covered. The complete
core fixture uses real descriptor/tar/ELF/shared-graph logic and all four helper
comparisons; signature and OS decoder primitives are mocked there. Such fixtures
are never actual signature/provenance qualification.

Initial portable fixture runs exposed the macOS /var → /private temporary-path
alias and an import performed while mocking sys.platform. The fixtures now use
canonical owned paths and load native-platform dependencies before mocking only
the API guard. No production path, platform or deadline rule was relaxed.
POSIX descriptor/private-mode cases are explicitly platform-limited; pure parser
and ordinary-API cases remain portable.

All eleven approved Ubuntu debs matched their exact compiled hash/size after
public HTTPS retrieval. Bounded preparatory inspection used only captured bytes
and the pre-existing local zstd decoder; it is not the fixed Linux signature or
dpkg-worker positive test. The first libc6 pass correctly refused unknown PLT
tags, and the nine-object batch exposed the missing libxxhash dependency. Those
findings caused explicit contract review/amendment before any extension.

After the amendment, one short preparatory static batch verified the exact libc
and libm layouts while the ordinary parser still refused those tagged objects.
The approved xxhash member is usr/lib/x86_64-linux-gnu/libxxhash.so.0.8.3,
71,832 bytes, SHA256 eae56344ba81fd5d25c6976028b33a53d3303848c382b04f3d5746549fb25228;
it declares only libc.so.6. All four shared-graph comparisons consume the full
selected union of 13 regular members and 10 aliases. No further declared dependency/tag
or path drift was found in that static batch. This establishes compatibility
of these public bytes with the static checks only, not signed origin, actual
loader behavior, runtime trust or production admission.

Scratch evidence is retained under the task-owned public candidate/preparatory
roots; no archive/generated artifact is tracked:

- /private/tmp/mentat-library-origin-amendment-light.log
- /private/tmp/mentat-library-origin-amended-static.log
- /private/tmp/mentat-library-provenance-preparatory-20261019/amended-static-check.json

## Initial source-review checkpoint

At this initial checkpoint, root and independent source reviews, the unchanged
tracked-secret scan and exact wheel/sdist/installed-module checks remained
pending. The baseline still contained the original 217 current-host entries.
Actual scanner findings required public-hash review before any baseline addition;
no detector, filter, threshold or broad exclusion changed. Later sections record
the completed source, baseline and package gates.

The three new Mentat modules are discovered by the existing explicit mentat
package and strict verifier's package-source inventory; no data resource or
public module list change appears necessary. At this checkpoint, the exact-branch artifact check and installed module byte
identity were still pending. The final evidence below records that separate
component build.

No operator Linux host is configured. Actual fixed Linux signature/decoder/
worker positives, complete loader/IFUNC/rewrite behavior, immutable launches,
privilege/FUSE teardown, the separate 14-member sealed Hermes/Python image,
package security currency, provider policy/account/live qualification and Run
admission remain unclaimed. No model, credential, service, owner configuration,
production factory, runtime capability or dispatch path was used or changed.

## Source-review correction: complete ignored-stanza grammar

Root and independent source review identified one gap: the reused helper tuple
selector bounded ignored stanzas but did not validate all their field syntax.
The library-private predecoder path now validates every deb822 stanza, including
ignored packages, using UTF-8 values, ASCII field names, case-insensitive duplicate
rejection, proper continuations and exact line/stanza/termination bounds. Binary-
index comments, orphan/whitespace-only continuations, folding of the fixed simple
coordinate fields, malformed/empty fields, invalid controls/UTF-8 and incomplete
stanzas refuse. Ordinary helper selection/policy remains unchanged. This follows
the [Debian control-file syntax](https://www.debian.org/doc/debian-policy/ch-controlfields.html#syntax-of-control-files);
it does not assign semantic authority to ignored package fields.

Three new methods include a complete UTF-8/multiline positive, within-bound
ignored malformed/duplicate/case-variant/continuation/termination negatives below
the raw hash guard, and a captured-core failure fixture whose private expected
hashes are updated to prove that grammar rejection precedes both decoder and
member-profile calls. Such fixture-only pin patches are not a production input.

The affected group ran 51 methods: 50 passed and the same actual-Linux method
skipped, in 0.395 seconds with ResourceWarnings as errors. Both retained real raw
indices also pass the private whole-index grammar, unchanged: 7,581,722 and 3,927,317
bytes with their original pinned SHA256 identities, in 2.132 seconds combined.
That is grammar compatibility only, not signature/origin/Linux qualification.
Logs: /private/tmp/mentat-library-origin-grammar-focused.log and
/private/tmp/mentat-library-origin-actual-index-grammar.log. At this correction checkpoint, the scanner findings and final artifact gate
were still pending; the 217-entry baseline remained untouched for explicit
public-hash review.

## Reviewed public-hash baseline ownership

Root and independent source review cleared exact bf25185 after the grammar
correction. Both also independently cleared the unchanged scanner's 28 actual
new public SHA256 occurrences: 15 in the fixed origin module, 2 in the exact-member
PLT module and 11 in the contract's JSON package tuples. Every detector fingerprint
matches its exact public literal already recorded in the reviewed contract.
Only those 28 is_secret: false records were added. The complete original 217 entries
and every non-results baseline field remain exact, for 245 total entries. No
credential, detector/filter/threshold change or broad exclusion was introduced.
The unchanged tracked-secret gate and exact-branch artifact checks subsequently
ran on the baseline-owner commit identified below.

## Final portable/security/package evidence

On baseline-owner head d9b3ae2c4dfe97b582a19a41c65d4721fe318476, the unchanged
tracked-file secret gate passes with 245 reviewed entries. Root and the independent
reviewer cleared exact bf25185 source and the 28-row public-hash packet before
that baseline update. The complete original 217 records and non-results metadata
were rechecked exact. No scanner or policy bypass was used.

One real no-isolation build creates the sdist and builds its wheel. The unchanged
strict verifier passes exact public membership, wheel RECORD integrity and
private-file exclusions. All 2,635 public source members in the sdist match the corresponding component
source files. All 1,108 tracked Git blobs remain exact before and after the
build. These checks use the exact component source graph.

Only the actual frozen Next runtime was reused: web source equality to 1c33 was
proved; its 2,451 runtime files, totaling 24,817,140 bytes, have canonical manifest SHA256
ffefc85397738902015943646ec78e3daea943b4983e33ab3593de7654412bbe before copy,
after copy, after normal staging and after the build. Frozen checkout head,
clean state and runtime bytes remain unchanged. No Next rebuild or app launch.

A fresh offline --no-index/--no-deps installation imports all three new modules
plus the two shared modules with exact source byte identity. It confirms the
11 compiled packages, 19 fixed inputs, 15,573,045 captured-byte identity sum and two
exact glibc profiles; the ordinary tag set excludes the new triple and freshness
remains false. No Linux signature/decoder/worker or loader qualification is
inferred from imports or compiled constants.

| Artifact | SHA256 |
|---|---|
| mentat_local-0.1.0b1-py3-none-any.whl | c4e94e2d891c6d72de9b837e4c0b4cb5315050d13451e7970d46253dd75031f9 |
| mentat_local-0.1.0b1.tar.gz | 93a3237197fa0dee23ca41e33bfcb23650faa506d020e64dba102046d4e672ca |

Artifacts, exact source/runtime manifests, verifier/install logs and result.json
remain only in /private/tmp/mentat-library-package-gate.s19hmjsr. The unchanged
secret-gate log is /private/tmp/mentat-library-origin-secret-gate-final.log.
This final record changes no packaged source, input pin, baseline or runtime
byte. Actual Linux signature/origin/worker, loader/rewrite/IFUNC/FUSE/immutable
launch, sealed runtime image, package currency, provider and Run qualification
remain separate unresolved gates. No production capability or readiness is
claimed by these completed Mac artifact and portable-source checks.
