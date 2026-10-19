# Fixed helper libraries: signed-origin verification contract

Status: contract and test strategy only, awaiting root and independent review.
No library verifier, worker, readiness record or execution integration is added.
Base: current host trust `78f778951f1abdde146264141e22c74126bd2a43` (PR324),
a normal descendant of original host trust508 and pure current-storage302.
The paused `codex/project-library-provenance` reference remains unchanged at508.

## Existing authorization and this slice

[Approved controller work](https://github.com/hazeion/agent-os/issues/239) says
“Implementation and qualification are authorized” and requires the contract/test
strategy before implementation. Its
[recorded next dependency](https://github.com/hazeion/agent-os/issues/239#issuecomment-5922242612)
explicitly includes immutable helper/loader closure and signed system libraries.
Root confirmed that this credential-free prerequisite falls within that
implementation authorization. This document narrows the work to public signed
byte relations for the four existing helpers and their static library/loader
closure on Ubuntu26.04 amd64. It does not authorize a new execution architecture.

The four helper identities remain exactly project_system_origin.PINS: bwrap,
squashfuse, fusermount3 and mksquashfs. Their supplied immutable ELF bytes must
match those existing size/SHA256 pins; no caller can select another executable.
Existing project_runtime_host_trust ELF and graph policy remains unchanged.

The separate fourteen-member sealed Hermes/Python library image is out of scope.
Its operator manifest, image authority and qualification remain unchanged. No
loader execution, FUSE, privileged helper execution, installed-host comparison,
production trust/witness/receipt, provider, account, model, Run, dispatch or
admission capability is introduced. Package safety/security-update currency,
complete dynamic loading and actual Linux execution remain unqualified. No
operator Linux host is configured or invented.

## Fixed data boundary

Proposed entry point: verify_fixed_helper_library_origins(root), a private fixed
worker operation over one owner-private staged directory. It has no browser,
bridge or ordinary runtime route, downloader, resolver, installer or caller pin
argument. The directory has exactly eighteen named regular inputs: the two
InRelease files, two raw main/binary-amd64 Packages indices, ten exact deb
basenames below and four existing fixed helper ELF files. No arbitrary filename,
package, suite, architecture, keyring, command, environment or loader path is
accepted. Missing, additional, redirected, duplicate or replaced inputs refuse.

Pin root/parent/file descriptors and identities; owner-private0700 directories,
regular0600 owner files, nlink1, no symlink/reparse entries and bounded sizes are
required before/opened/after reading and terminal path checks. Open nonblocking
and no-follow so regular-to-FIFO races refuse before reading. Snapshot inputs
once, retain ownership through verified worker teardown and compare unchanged
source identity/metadata. Only captured immutable bytes reach verification.

A successful immutable result contains the fixed package tuples, selected
regular member path/SHA256/size, authenticated alias text and four static closure
comparisons. No package text, private path, arbitrary command output, signature
blob or executable bytes cross the bounded report channel. The caller can copy
or construct such data, so it is explicitly not a capability or execution
witness. Existing host-closure required_qualification flags are not cleared or
rewritten. Results are not saved as trusted readiness state.

## Trust chain, dates and replay

The trust anchor remains the existing Ubuntu Archive2018 full signing fingerprint
F6ECB3762474EDA9D21B7022871920D1991BC93C. Signature verification uses only the
fixed OS /usr/bin/gpgv with its fixed /usr/share/keyrings/ubuntu-archive-keyring.gpg,
a disposable empty homedir, bounded status output and one exact authenticated
clear-signed message. The OS, kernel, keyring, gpgv and dpkg-deb are explicitly
trusted inspection primitives; this slice does not self-qualify them. Owner
keyrings, network key lookup, imported keys, fallback signers and trust-on-first-
use are forbidden. Reject missing/bad/expired/revoked signature status, multiple
signatures/messages, unsigned prefixes/suffixes, bad dash escaping and ambiguous
status/fields. Require the exact primary signing identity, not a short key ID.

Require Origin=Ubuntu, Label=Ubuntu, Version=26.04, Codename=resolute, exact Suite,
and amd64 in the authenticated Architectures field. Index selection is exactly
main/binary-amd64/Packages in its chosen suite. Reject duplicate fields, duplicate
index coordinates, wrong index size/digest, extra matching package stanzas,
missing newline termination and malformed/oversize ignored stanzas too. Deb
Package, Version (including epoch), Architecture, Filename, Size and SHA256 must
match the compiled tuple exactly; Architecture=all or amd64v3 is not substituted.

These are closed historical snapshot comparisons. Compile exact InRelease
size/SHA256 and authenticated Date values below, along with exact index
size/SHA256. Replaying another signed snapshot, including a newer one, refuses;
repeating the exact selected snapshot is allowed as reproducible origin evidence.
Both selected releases omit Valid-Until: compile that absence explicitly and
reject duplicate, malformed or unexpected Date/Valid-Until fields. No clock
window or absent expiry is silently interpreted as current security freshness.
Return snapshot dates and freshness_qualified=false. A claim requiring live
freshness or a security-current package set must refuse/defer to a separately
reviewed current security-pocket qualification; this operation cannot satisfy it.
There is no mutable last-seen-date database or anti-rollback authority to invent.

| Snapshot input | Bytes | SHA256 | Authenticated Date expected |
|---|---:|---|---|
| resolute.InRelease | 135549 | 45f95ce276cdba3e41870516a130e03c58b8b7a79e9546b0efe9e526d255740c | 2026-04-23 17:07:15 UTC |
| resolute-updates.InRelease | 137401 | e5b34d880415a65eb1412e2580a72696937f30d754d312fdbd26e25283f0b4e2 | 2026-10-19 18:03:58 UTC |
| resolute-main.Packages | 7581722 | 92eb335c0ed27983d41a5a0efdf0edce3e67bfa34e8e987af9df260ca72d9bf9 | inherited from resolute |
| resolute-updates-main.Packages | 3927317 | adbe8cefb6ae705c354c8d88b7e303738266d6a213c75a1426887ab99f0f49f1 | inherited from resolute-updates |

Raw hashes, sizes, field values and index hash relations above were read from
existing public scratch bytes only. This contract preparation did not verify a
signature, fetch a deb or claim that those raw inputs are authenticated. The
future verifier must establish the complete chain before accepting any member.

## Proposed compiled package pins and deterministic selection

Ten package tuples are reconstructed from the two existing raw indices. libc6
and zlib1g select resolute-updates/main; all others select resolute/main. This is
a closed explicit coordinate list, not semver resolution, latest-available
selection or a search across pockets. No security/restricted/universe/PPA index
is consulted. In particular the base/updates-only choice is not a claim about
security-pocket coverage, package safety or installed-host provenance.

All ten are amd64, component main, with pool-relative paths restricted to the
exact compiled string. The fixed public source is archive.ubuntu.com/ubuntu;
this operation performs no download. Each archive must match its exact size and
SHA256 before any decoder invocation. Combined deb bytes are3218102; the four
metadata inputs total11781989 bytes. No member digest is invented or accepted
from the caller: selected aliases/regular-byte identities derive only from these
authenticated exact archives, and the output records them for review.

```json
[
  {
    "package": "libc6",
    "version": "2.43-2ubuntu2.4",
    "suite": "resolute-updates",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/g/glibc/libc6_2.43-2ubuntu2.4_amd64.deb",
    "size": 2104056,
    "sha256": "a613b457f3ff9c84ebd28af8a05afdec22605ad9aed87c71e3a6ae5170aeb9ca"
  },
  {
    "package": "libcap2",
    "version": "1:2.75-10ubuntu2",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/libc/libcap2/libcap2_2.75-10ubuntu2_amd64.deb",
    "size": 29264,
    "sha256": "150603a0792b1d22aa0bde0a26c27b413018c799284003e4b43cba587a5b3a18"
  },
  {
    "package": "libfuse3-4",
    "version": "3.18.2-1",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/f/fuse3/libfuse3-4_3.18.2-1_amd64.deb",
    "size": 92984,
    "sha256": "59ae972173e389eb981aaeae874b3d6aafe7eceff284f94e5c21ee1d049548c6"
  },
  {
    "package": "liblz4-1",
    "version": "1.10.0-8",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/l/lz4/liblz4-1_1.10.0-8_amd64.deb",
    "size": 73784,
    "sha256": "28fe729f69be0fa950618f0ee02e479218fd60b11e86c1aa6026c87632ed2aa4"
  },
  {
    "package": "liblzma5",
    "version": "5.8.3-1",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/x/xz-utils/liblzma5_5.8.3-1_amd64.deb",
    "size": 145410,
    "sha256": "38ad8500817a9159db210fecfb8c50fa82d7a8829730fcdf8ae60e3523676d41"
  },
  {
    "package": "liblzo2-2",
    "version": "2.10-3build2",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/l/lzo2/liblzo2-2_2.10-3build2_amd64.deb",
    "size": 55968,
    "sha256": "ffc9f1fea544f200b7b47a77e0ec89f70d493b5393ea2f7a43f6b9685b3341b8"
  },
  {
    "package": "libpcre2-8-0",
    "version": "10.46-1build1",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/p/pcre2/libpcre2-8-0_10.46-1build1_amd64.deb",
    "size": 256534,
    "sha256": "3e116766f1a7b149994d4745556023d993d26401223d1595520a991d4ba737fb"
  },
  {
    "package": "libselinux1",
    "version": "3.9-4build1",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/libs/libselinux/libselinux1_3.9-4build1_amd64.deb",
    "size": 90316,
    "sha256": "3ce3aea44b2ec00780c48b1b8e1f7e672166ec3ccac14b0eae8890e55983061e"
  },
  {
    "package": "libzstd1",
    "version": "1.5.7+dfsg-3",
    "suite": "resolute",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/libz/libzstd/libzstd1_1.5.7+dfsg-3_amd64.deb",
    "size": 308174,
    "sha256": "34365d611ccf1f717f90a92fbe52ed96ae1829ab9be363c68a83563322797f8f"
  },
  {
    "package": "zlib1g",
    "version": "1:1.3.dfsg+really1.3.1-1ubuntu3.1",
    "suite": "resolute-updates",
    "component": "main",
    "architecture": "amd64",
    "filename": "pool/main/z/zlib/zlib1g_1.3.dfsg+really1.3.1-1ubuntu3.1_amd64.deb",
    "size": 61612,
    "sha256": "450d9322ac4e9baea0f9a74548a20fde73b078235c1f5d1fb7084c2638e33cdd"
  }
]
```

## Closed selected member and alias graph

The compiled SONAME roots are libc.so.6, libm.so.6, libselinux.so.1, libcap.so.2,
libpcre2-8.so.0, libz.so.1, liblzma.so.5, liblzo2.so.2, liblz4.so.1, libzstd.so.1
and libfuse3.so.4 under /usr/lib/x86_64-linux-gnu, plus the fixed interpreter
/lib64/ld-linux-x86-64.so.2 (the existing canonical /usr/lib64 alias). Package
ownership is explicit: libc6 owns libc/libm/loader; each other root belongs to
its named package. The pcre2 root is a proposed recursive dependency of selinux,
not a declared complete closure proven by this metadata-only preparation.

Read only the authenticated package's data tar through fixed dpkg-deb
--fsys-tarfile on sealed captured archive bytes. Never install, extract to a host
path, invoke maintainer scripts, run an ELF/ldd, load a library, inspect the host
loader cache or query installed package metadata. Scan bounded raw tar headers
before allocation. Accept at most one conventional leading ./ on archive names;
reject absolute names, redundant separators, dot/dotdot components, duplicate
canonical members, sparse/PAX/GNU extensions and unsupported controls. Account
for ignored member payloads and padding. Selected hardlinks and special files
refuse. Ignore only bounded unselected package members; do not interpret them.

Follow selected symbolic links only within that authenticated package and the
fixed library roots. Preserve each exact alias string in the result; reject
loops, escape, cross-package links, ambiguous targets, excessive depth and
unselected shadow objects. Never create these links on the host. Only the
existing fixed /lib→/usr/lib and /lib64→/usr/lib64 namespace spelling maps apply;
no new mount or filesystem alias is created. Root paths are explicit, not a
caller glob or host-directory search. Refuse absent or multiply defined selected
members instead of choosing a convenient ABI/library version.

Inspect each selected regular object with the unchanged strict host ELF policy:
ELF64 little-endian machine62 only, fixed interpreter, closed dynamic-tag/flag
policy, no RPATH/RUNPATH, unsupported search/loader/audit/plugin features or
ambiguous mappings. Validate its selected SONAME (the fixed loader may have no
SONAME) and resolve only represented authenticated aliases. Construct each
helper's reachable subgraph, then call the existing host-closure audit unchanged.
Every union member must be needed by at least one helper; every per-helper member
must be consumed. Any missing extra recursive dependency refuses. Extending the
package/root list requires a contract/pin review, not an automatic download.
No static result proves cache/preload/hwcaps/dlopen/NSS/plugin/implicit-subprocess
behavior, immutability at launch or FUSE privilege/teardown.

## Bounds and ownership

Inputs: exactly18 regular files; InRelease ≤256KiB each; raw Packages ≤16MiB
each, with64KiB line/stanza ceilings; each deb ≤4MiB and its exact compiled size;
helper ELF bounds remain the existing exact PINS sizes. Fixed aggregate hard
ceiling is80MiB, checked before capture/allocation (actual selected metadata and
deb inputs15000091 bytes plus547152 helper bytes). Tar stdout ≤32MiB per archive,
≤320MiB cumulatively scanned; selected regular bytes ≤32MiB total, each ≤16MiB;
≤64 selected regular/alias members total, alias depth≤16, path length≤512 and
canonical components≤255 characters. No allocation follows an unchecked tar
size, nested extension or declared compressed size.

A fixed credential-free worker retains512MiB address-space,15 CPU-second,64-FD
and zero-core limits. Signature stdout/stderr and decoder stderr are each≤16KiB;
normalized public result≤16KiB. Commands are serial and fixed argv; descriptors,
not checked-then-reopened pathnames, identify captured inputs. The existing
30-second absolute acceptance budget includes commands and verified owned
cleanup; no retry, budget expansion or late success is added. Only exactly owned
children/groups may be signaled, retained until leader/reader/group quiescence
is proven. Do not reap then signal a reusable numeric PID/group. Uncertain
cleanup retains ownership and cannot emit success; OS creation/unverified
cleanup is not promised to finish within that acceptance budget. No discovery-
PID kill, lazy detach, filesystem cleanup of unverified state or global service
operation is introduced. These bounds require review against actual selected
archive sizes before implementation, not a configurable generic command runner.

## Test strategy and review gates before implementation

1. Pure hostile fixtures cover exact tuple/signature status/frame/date/expiry/
   suite/component/architecture/index matches; unsigned or spliced messages,
   wrong primary key, extra signatures, changed dates, missing/duplicate fields,
   alternate/newer/older snapshot replay, forged hashes and valid-but-wrong-pocket
   metadata all refuse. Exact frozen snapshot replay succeeds only as historical
   origin comparison and always retains freshness_qualified=false.
2. Package tests cover exact authentic hash/size before decoding, missing/extra/
   duplicate stanzas and filenames, epoch versions, truncated input, oversized
   ignored stanzas, hash mismatch and decoder-not-called on refusal. A positive
   fixture exercises real bounded decoding behavior without executing package
   contents; no caller-supplied boolean/report can manufacture provenance.
3. Tar/alias/ELF fixtures cover hostile allocation declarations, extensions,
   traversal, duplicate paths, hardlinks/special files, alias escape/cycle/depth,
   conflicting SONAME/package ownership, architecture/mapping/tag/search-policy
   drift, missing/unused closure objects and fixed helper digest mismatch. Keep
   valid selected symlinks and the fixed loader positive path.
4. Filesystem/worker tests cover replacement, same-inode chmod/hardlink, FIFO,
   short reads, root/file identity drift, command output flood, child exit with
   live descendant/reader, timeout and cleanup uncertainty. Every failure leaves
   public source bytes unchanged, performs no package install/library load and
   emits no successful result after deadline. Tests must prove actual ownership,
   not mock cleanup reports as successful evidence.
5. After root plus independent contract clearance, implement only this boundary,
   then obtain two adversarial source reviews, unchanged focused tests, actual
   signed-public-input positive checks where trusted tools exist, unchanged
   tracked-secret scan and exact wheel/sdist/installed module checks. New public
   pin findings need exact reviewed baseline entries, no detector/threshold or
   broad exclusion changes. No fetched package or generated artifact is tracked.
6. Actual Ubuntu host/library-loader/FUSE/immutable-launch and complete execution
   qualification stay separate, currently unrun without a configured operator
   host. Portable tests, static graphs and signed-byte relations cannot replace
   them or qualify the separate sealed Hermes/Python14-member image. Provider
   policy implementation approval, account consent and live qualification remain
   pending under current239/234. No issue closure or production admission follows.

## Primary-source rationale and preparation evidence

Ubuntu documents the InRelease→Packages→deb digest chain and distinguishes an
archive trust anchor from transport; authentic archived versions can be checked
with preserved/snapshot metadata. This contract applies that relation only to
a fixed comparison and makes no installed-package or safety claim.
[Ubuntu archive integrity verification](https://documentation.ubuntu.com/security/software-integrity/archive-verification/).
The existing reviewed project_system_origin contract/code supplies the fixed
Archive2018 signer and trusted OS command boundary; their claims are not enlarged.

Preparation read only the existing two public releases/indices and the earlier
four-helper public ELF declaration report. Raw index sizes/hashes match the
corresponding SHA256 text entries; signatures and ten deb contents have not been
verified here. Existing full QA belongs to other exact heads, not this unimplemented slice.
No tests of this slice have run. No source module, public package, test,
credential or operator state changed; no runtime/archive artifact was downloaded.
Only official public documentation was read over the network.


## Proposed amendment A: observed glibc PLT metadata and missing xxhash

Status: awaiting root and independent contract review. The implementation still
rejects this drift. No parser policy, package pin, input count or source has been
extended by writing this amendment. If approved, this section supersedes only
the original ten-package/eighteen-input counts and the library-specific handling
specified here; every other boundary, deadline and exclusion remains unchanged.

### One bounded preparatory research batch

All ten public debs matched the original exact size/SHA256 pins after download.
One bounded compatibility batch inspected their already pinned data-tar bytes
with the existing local zstd decoder; it installed/extracted no filesystem tree,
loaded/executed no ELF and verified no signature. This is raw compatibility
research, not trusted Linux gpgv/dpkg-worker or provenance qualification.

Existing strict host ELF rejects three processor tags in the exact libc6 libc
and libm members. The other nine selected regular objects have no unknown tags
or duplicate singleton tags, but lz4 declares libxxhash.so.0 outside the original
closed list. Therefore the original full closure remains incomplete/refused.
This amendment addresses both findings rather than substituting a hash-only
success for the real closure check. The untagged loader remains an ordinary
strict-policy positive case.

Evidence retained privately:

- elf-contract-drift.json and libc6.tar under the task-owned preparatory root;
  raw tar SHA256 e1986a088b3154457aa9780a86abc10436f149ba910e7c6e97487a0c60045299,
 5652480 bytes. It came from the unchanged a613b457... libc6 archive above.
- remaining-nine-compatibility.json records exact public regular/alias paths,
  bytes/hashes, declared dependencies and mappings for the nine-object batch.
- The preparatory root is /private/tmp/mentat-library-provenance-preparatory-20261019.
  No local path is an authority input or a product lookup default.

Selected regular-member observations below are public facts from those exact
archives, not invented expected hashes or proof of signed origin. Their common
prefix is /usr/lib/x86_64-linux-gnu/.

| Package | Regular member basename | Bytes | SHA256 |
|---|---|---:|---|
| libcap2 | libcap.so.2.75 | 51616 | c5b463a8136dabb152bad8b04e89bf67bd2049ef49777ed0b96bdbc6cb5b9565 |
| libfuse3-4 | libfuse3.so.3.18.2 | 276784 | 2ab67cc34f294e2e9958889bb224ff72f507816c860726c89469ce488a3a610b |
| liblz4-1 | liblz4.so.1.10.0 | 166224 | 45729d07db6c43e524c2e69d0c4aef81148a66e272c4f4e0e64b787e17fe1731 |
| liblzma5 | liblzma.so.5.8.3 | 215448 | 64550dc7a4dc9159d32c00d9e78ce86e0951d02b7b24827df97f090dae101a19 |
| liblzo2-2 | liblzo2.so.2.0.0 | 149656 | 1728af970f1689da66c2314c328aef8fd21a7c42332469177914367f5082c086 |
| libpcre2-8-0 | libpcre2-8.so.0.14.0 | 699056 | 4a6b6b2078685b074869d75cb068664d7da6b3036df7bca0442b1bbbd4ac7e65 |
| libselinux1 | libselinux.so.1 | 199120 | 7538ee77765a27966563c0d22437a3080dcdb346ff76cc16d71a3ce3379a716a |
| libzstd1 | libzstd.so.1.5.7 | 796824 | 060eeb79531d435306665fd78329d8a9dd579f95876c5960bb67937825362a80 |
| zlib1g | libz.so.1.3.1 | 121272 | 47b61967895b30e8c0c6818dd633ffeb87711cf637c688f981896f0dd84ce23b |

### Explicit additional package/input proposal

liblz4.so.1.10.0 (166224 bytes,
SHA25645729d07db6c43e524c2e69d0c4aef81148a66e272c4f4e0e64b787e17fe1731)
declares libxxhash.so.0. The existing resolute/main raw amd64 index contains one
candidate tuple below; no archive has been fetched and its signature/member
contents have not been checked here. Approval would add only this exact package
and canonical SONAME root /usr/lib/x86_64-linux-gnu/libxxhash.so.0. Unknown
transitive dependencies still refuse and require review; no automatic resolver
or pocket/version fallback is introduced.

```json
{
  "package": "libxxhash0",
  "version": "0.8.3-2build1",
  "suite": "resolute",
  "component": "main",
  "architecture": "amd64",
  "filename": "pool/main/x/xxhash/libxxhash0_0.8.3-2build1_amd64.deb",
  "size": 25802,
  "sha256": "4fff119ba9018fbe2eddfa7759bb4c7b6132ed38dcfa7fc58750c586d1d155a1"
}
```

The amended inventory is exactly eleven packages and nineteen regular inputs:
two releases, two indices, eleven archives and four fixed helper ELF inputs.
Archive bytes become3243904; metadata plus archives15025893; adding the existing
547152 helper bytes gives15573045 captured bytes. Existing80MiB aggregate,
4MiB-per-archive,32MiB-selected-byte,64-member,320MiB-cumulative-tar, worker and
30-second acceptance/cleanup limits remain unchanged. The full authenticated
raw-index identities, frozen dates, key, historical replay semantics and
freshness_qualified=false remain unchanged. Do not fetch the new archive before
this explicit inventory amendment is approved.

### Processor-tag source and exact-member restriction

The primary [x86-64 psABI MR50 diff](https://gitlab.com/x86-psABIs/x86-64-ABI/-/merge_requests/50.diff)
defines DT_X86_64_PLT (DT_LOPROC+0), DT_X86_64_PLTSZ (+1) and
DT_X86_64_PLTENT (+3) as PLT address, total bytes and uniform entry bytes. It
relates each JUMP_SLOT addend to its indirect-branch address and requires a
uniform aligned entry layout. [MR52](https://gitlab.com/x86-psABIs/x86-64-ABI/-/merge_requests/52.diff)
adds the power-of-two entry-size requirement. These declarations are not a new
object search or dependency mechanism; that does not make them inert.

GNU [ld mark-plt documentation](https://sourceware.org/binutils/docs/ld/Options.html)
records compatibility requirements for loaders interpreting relocation addends.
Upstream glibc [848746e88ec2aa22e8dea25f2110e2b2c59c712e](https://sourceware.org/pipermail/glibc-cvs/2024q1/083835.html)
implements conditional PLT rewriting after relocation, including writable code
pages restored to executable protection. The code depends on loader binding,
tunable and CPU/CET/APX conditions. No environment or GLIBC_TUNABLES change,
rewrite, IFUNC execution, mprotect, loader test or assertion of default runtime
behavior is authorized here. Actual code-rewrite/loader qualification remains
an explicit unresolved requirement even after this static profile passes.

An additional library-only profile may apply ONLY after authenticated extraction
of these two exact regular members from the original pinned libc6 archive:

| Member | Bytes | SHA256 | PLT address A | PLT bytes S | Entry bytes E | N |
|---|---:|---|---|---:|---:|---:|
| usr/lib/x86_64-linux-gnu/libc.so.6 | 2190608 | 85e64f97e348786a8fb4d9f3d52fec289e2fb86bba20f0731dfe61990525e0f7 | 0x283f0 | 960 | 16 | 60 |
| usr/lib/x86_64-linux-gnu/libm.so.6 | 1198376 | 1c488db6f4fe8cecb72456bc018de000b7a9b539c2994864b0416b5e8371b3d8 | 0x12320 | 736 | 16 | 46 |

No global dynamic-tag whitelist changes. Ordinary host-helper validation and
all other objects retain their current unknown-tag refusal. Do not strip tags,
rewrite bytes, pass a caller allowlist/hook, silently choose a different member
or let this exception apply merely because an object calls itself libc/libm.
The public package, exact member path, size and digest all select the context;
raw bytes remain unchanged. The existing loader member is254864 bytes,
SHA256bda779ea9e9ad234f60315477d7cfd0bdde861cd8ddd9df8cdaf62f18c4cec14,
and must pass the unmodified policy with no tag triple.

### Closed bounded PLT/relocation checks

All three new tags must be absent together under the old policy or present
exactly once each in this exact library context. Partial/duplicate triples,
other processor-specific tags, zero values and every other existing forbidden
flag/tag/search declaration refuse. For the tagged two objects require the
exact table values above, E=16 (also a power of two), A aligned to E,
S divisible by E and S/E=N. All address additions/multiplications must stay in
unsigned64-bit range before reading a bounded file slice.

The entire PLT range must have one unambiguous contiguous file-backed PT_LOAD
mapping with PF_R|PF_X and no PF_W. No BSS-only bytes, hole, alias or interior
conflicting mapping is accepted. Each16-byte entry must be exactly:

```text
F3 0F 1E FA FF 25 <signed little-endian disp32> 66 0F 1F 44 00 00
```

Interpret only that fixed byte template; do not disassemble or simulate code.
Derive its GOT address as entry_address+10+signed_disp32 with checked arithmetic.
The slot must be unique,8-byte aligned and wholly inside one readable/writable,
non-executable file-backed mapping. No actual memory, GOT write or indirect
branch is performed.

Require DT_PLTREL=7 (RELA), DT_RELAENT=24, and a uniquely readable, file-backed
DT_JMPREL array with DT_PLTRELSZ=24*N. Every entry has exactly one corresponding
unique GOT/r_offset relocation and vice versa. Only R_X86_64_JUMP_SLOT (7) and
R_X86_64_IRELATIVE (37) are represented in this fixed table: libc requires15/45
and libm11/35 respectively. Reject missing, extra, duplicate, unsupported or
misaligned records and unmapped table/slot intervals.

For JUMP_SLOT require r_addend=entry_address+4 (the indirect branch), symbol
index>0 within the validated dynamic symbol count, and a bounded referenced
symbol/name/version. For IRELATIVE require symbol index0 and a nonzero resolver
addend in a unique nonwritable executable file-backed range. Its addend is a
resolver address, NOT a PLT entry/branch address. Do not invoke it or claim the
resolver's behavior is qualified; checking an address is not checking code.

### Symbol/version bounds and ABI marker

Require the observed SysV DT_HASH and GNU_HASH tables, each fully file-backed
and readable, with bounded validated header/count/index/chain structure and
consistent dynamic-symbol bounds. Do not infer an unbounded symbol table from
a relocation index alone. Proposed hard caps are65536 dynamic symbols/hash
buckets/chains,8192 GNU bloom words,1MiB dynamic strings and4096 total linked
version records/auxiliary records. These caps only bound metadata processing;
all existing ELF/header/dynamic/string and selected-object byte ceilings stay.
Reject zero/overflowing counts, out-of-range or cyclic chains and inconsistent
table bounds; if the tables cannot prove the symbol count, retain refusal.

DT_SYMENT must be24; every referenced symbol record and VERSYM entry must fit
inside uniquely mapped readable file data. Its string offset must lie within
the bounded DT_STRTAB/DT_STRSZ and terminate there without crossing the table.
Bound referenced symbol/version/provider strings to255 printable ASCII bytes.
Version indices0/1 remain reserved; every other referenced index must resolve
unambiguously through validated VERDEF/VERNEED records. Bound all list and aux
counts, offsets, alignment, termination and visited ranges; reject cycles,
overflow, overlaps, duplicate identities and contradictory indices/providers.
Never follow an unchecked offset or allocate from a declared count.

Require libc VERDEF to define exactly the compatibility marker
GLIBC_ABI_DT_X86_64_PLT, and libm VERNEED to require it specifically from
libc.so.6. Validate associated record/index/string/hash relations rather than
searching for marker text anywhere in the file. The upstream marker is recorded
in [glibc399384e0c8193e31aea014220ccfa24300ae5938](https://sourceware.org/git/gitweb.cgi?p=glibc.git;h=399384e0c8193e31aea014220ccfa24300ae5938)
and [backport269e89bd8d25a0659c6c963a509e152faefd6ba2](https://inbox.sourceware.org/glibc-cvs/20250815212354.698B23858CDA%40sourceware.org/T/).
It is compatibility metadata, not proof of an installed loader's behavior,
immutable execution trust or permission to rewrite code. No provider/version-
name substitution satisfies this check.

### Amendment adversarial strategy and hold

Add meaningful low-level metadata fixtures that reach each validation rule;
mutating bytes and failing only the outer exact-hash guard is insufficient
coverage. Fixture-only internal pin patches cannot be a production override.
Test missing/duplicate/partial triples, wrong E/alignment/S/count/overflow,
W|X/BSS/hole/overlapping mappings, changed opcodes/NOP/branch displacement,
aligned-but-wrong/duplicate/unmapped GOT, RELA size/type/count/target drift,
wrong JUMP addend, nonzero IRELATIVE symbol or invalid executable resolver,
invalid symbol/hash/chain/string/version bounds and a forged/missing/wrong-
provider ABI marker. Keep both exact public members and the untagged loader as
positive static cases once permitted; all other processor tags/layouts refuse.
Test that the ordinary host-helper API still refuses the tagged libraries.

Add the explicit eleventh package/nineteenth input only after this amendment is
cleared; require unchanged signed-index selection and fail before decoder on
missing/changed/extra input, wrong tuple or archive bytes. Decode its selected
SONAME/member graph only after that approved fetch, record actual member
hashes, and refuse any additional dependency/tag/path/layout drift for review.
No package safety/freshness, provider, loader, sealed14-image, FUSE, witness,
Run or production gate is cleared. No mock is labeled actual Linux signature
verification. Preserve30-second cleanup/deadline and every original ownership
and byte bound; no tests/build/decoding resume while root holds the browser CPU
window. Implementation remains paused until root and independent review of this
complete amendment, with code-source reviews and unchanged gates afterward.
