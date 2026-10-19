# Signed helper-library historical-origin implementation candidate

Status: local source-review candidate, not published or release/runtime qualified.
Contract history is52bbc39 → eea55f0 → e6145e6. The parent current host-trust
commit is78f778951f1abdde146264141e22c74126bd2a43, and the original paused508
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
environment, absolute30-second acceptance budget and verified owned-group
cleanup pattern. Uncertain/late results cannot succeed. The result is immutable,
freely constructible static data, never a witness or readiness state. Its
freshness flag remains false, with explicit security-current, sealed-image,
loader, glibc-rewrite/IFUNC, immutable-helper, FUSE and production-runtime gaps.

project_library_plt selects its profile only for the compiled path/size/SHA256
of the two authenticated libc6 members. It checks the exact CET16 entry tables,
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

The short affected portable group ran48 methods:47 passed and one actual-Linux
integration method skipped, in0.320seconds, with ResourceWarnings as errors:

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

Initial portable fixture runs exposed the macOS /var→/private temporary-path
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
71832bytes, SHA256eae56344ba81fd5d25c6976028b33a53d3303848c382b04f3d5746549fb25228;
it declares only libc.so.6. All four shared-graph comparisons consume the full
13-regular-member/10-alias selected union. No further declared dependency/tag
or path drift was found in that static batch. This establishes compatibility
of these public bytes with the static checks only, not signed origin, actual
loader behavior, runtime trust or production admission.

Scratch evidence is retained under the task-owned public candidate/preparatory
roots; no archive/generated artifact is tracked:

- /private/tmp/mentat-library-origin-amendment-light.log
- /private/tmp/mentat-library-origin-amended-static.log
- /private/tmp/mentat-library-provenance-preparatory-20261019/amended-static-check.json

## Remaining source and qualification gates

Root and independent adversarial source reviews are required on the exact
committed candidate. Additional affected parser/origin/image tests, unchanged
tracked-secret scan and exact wheel/sdist/installed-module verification remain
pending the browser quiet-window release. The baseline remains the unchanged
217-entry current-host baseline. New public immutable pin/member hash literals
need review of actual findings from the unchanged scanner before any exact
baseline additions; no detector/filter/threshold or broad exclusion is changed.
No scanner pass is claimed for this source yet.

The new three mentat modules are discovered by the existing explicit mentat
package and strict verifier's package-source inventory; no data resource or
public module list change appears necessary. A real exact-branch artifact check
must confirm that inference before publication, including installed module byte
identity. Do not reuse an aggregate wheel as this branch's archive graph.

No operator Linux host is configured. Actual fixed Linux signature/decoder/
worker positives, complete loader/IFUNC/rewrite behavior, immutable launches,
privilege/FUSE teardown, the separate sealed Hermes/Python14-member image,
package security currency, provider policy/account/live qualification and Run
admission remain unclaimed. No model, credential, service, owner configuration,
production factory, runtime capability or dispatch path was used or changed.
