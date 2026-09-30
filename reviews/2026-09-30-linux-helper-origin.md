# Fixed Linux helper public origin

Status: implemented private component within approved isolated-worker qualification.
The tested host is Ubuntu 26.04 amd64. This slice proves selected helper bytes
against public signed package metadata; it grants no Run or readiness authority.

The four fixed executables are bwrap, squashfuse, fusermount3 and mksquashfs.
Pin their exact Ubuntu package/version/archive SHA-256/size and member names in
code. Verify each origin chain: the public Ubuntu Archive 2018 full fingerprint
authenticates a bounded InRelease; its SHA-256 authenticates the complete raw
Packages index; an exact package tuple selects the already staged archive;
its pinned SHA-256 and size authenticate bytes before archive decoding. Finally
compare the selected regular member's bytes against the current root-owned,
no-follow installed executable. Retain only bounded public digest evidence.
Pin release Origin/Label/Codename/Suite and exact component/amd64 index path.
Bubblewrap selects resolute-updates/main; squashfuse selects resolute/universe;
fuse3 and squashfs-tools select resolute/main. Require one exact canonical
selected stanza in that coordinate. This proves a signed byte relation, not
which mirror/pocket originally installed a file on this host.

Staged inputs live in an operator-owned private directory and are opened
descriptor-relative without following links. Require regular owner files,
safe modes and byte ceilings; retain the original descriptors and recheck
directory/name/file identities and attributes through the complete operation.
Decode only verified immutable captured bytes or their sealed memory FD,
never reopen a pathname after checking its digest. Refuse replacement.

Use the fixed Ubuntu public keyring with credential-free gpgv and exact signer
status checks. Treat the installed OS, kernel, gpgv and dpkg-deb as trusted
verification tools, not as artifacts newly qualified by this comparison.
No package install, maintainer script, package executable, owner keyring,
credential, service, APT refresh or configuration change is allowed. Staged
public metadata/packages are inputs, not a browser fetch/read capability.
Derive fields only from authenticated clear-signed plaintext with one exact
message/signature frame and bounded dash escaping. Reject unsigned prefixes,
suffixes and extra payloads; a successful signer status cannot bless them.

Run signature checking and verified-package tar expansion only in a fixed
credential-free worker. Bound raw releases to 256 KiB, each index to 128 MiB,
index lines/stanzas to 64 KiB, each archive to 16 MiB, expanded tar to 32 MiB,
selected members to 16 MiB, and command replies/normalized result separately.
Exactly two releases, three raw index coordinates and four archives are input;
their aggregate ceiling is 448.5 MiB. Worker limits are 512 MiB address space,
15 CPU seconds, 64 descriptors and zero core size. Signature stdout/stderr and
decoder stderr are each capped at 16 KiB; decoder stdout is the 32 MiB tar
ceiling and one normalized result is at most 4 KiB. Check raw tar headers and
bounded PAX/GNU metadata before tarfile allocation; reject sparse declarations,
bound extension depth, and charge ignored members/padding too.
The implemented narrow decoder rejects all PAX/GNU extension and sparse
metadata before processing their declared payload; selected members must be
regular files. It parses only bounded raw 512-byte headers and never extracts.
The parent enforces a fixed 30-second evidence acceptance deadline including
verified cleanup and kills its owned worker tree on expiry, without replay.
As with scope inspection, OS creation/unverified cleanup cannot promise bounded
return time; late matching evidence cannot escape. Never extract archive paths
onto the host. Reject duplicate/noncanonical paths, links for selected members,
unsupported types, malformed controls, wrong identity/signature/digest and
source replacement. No arbitrary executable, environment or command is input.
Command cleanup retains each exact unreaped child and drains it before any IPC
outcome. Parent teardown records ownership before inherited cleanup, verifies
leader/reader and complete trusted-command group quiescence, and retains the
owner on unverified cleanup. Subsequent checks only observe; they never repeat
group signals against a potentially reused numeric ID. Trusted OS verification
tools and their descendants are assumed to inherit the owned worker group.

This is origin evidence, not package safety, security-update currency, immutable
helper execution, complete dynamic-loading closure, provider/model qualification
or Project admission. Those gates remain required; the schema-41 guard stays.
The helper executables/libraries must still be pinned at launch before this
proof could contribute to production qualification.

Test hostile metadata/archive/protocol inputs, symlink/replacement and installed
byte mismatches. Use the actual public signed Ubuntu indices and four matching
archives on Linux, with no package execution or owner-state change. Obtain two
independent reviews and package verification before publishing a full PR.

Primary authority: [Ubuntu archive integrity verification](https://documentation.ubuntu.com/security/software-integrity/archive-verification/)
describes the signed InRelease → SHA-256 Packages → archive chain;
[Ubuntu's published Archive 2018 fingerprint](https://lists.ubuntu.com/archives/foundations-bugs/2020-May/422926.html)
anchors the fixed signing identity.

## Preliminary actual-host evidence

Read-only public-artifact inspection verifies the Ubuntu Archive 2018 signer,
six complete cached index hashes (93,311,314 bytes) and four pinned archives
(334,310 bytes). The selected two release/three index coordinates authenticate
the four exact compiled tuples. From kernel-sealed captured archive inputs,
fixed dpkg-deb emits tar without installation or maintainer-script execution;
each selected regular executable equals the installed root-owned bytes.
All four comparisons match, totaling 547,152 executable bytes. Original staged
file/directory identities remain unchanged during this inspection.

This preliminary script is separate from the fixed product worker and does not
itself prove hostile-input/resource or supervision guarantees. Both contract
and final code reviews are clear after correcting cleanup ownership/no-resignal
state and the size ceiling for ignored metadata stanzas. The final Linux
helper/scope/public-origin group passes all 51 methods without skips, including
the actual fixed worker's four signed helper comparisons. Windows passes the
34-method helper/public-origin group with nine Linux-only skips; all 12
portable helper methods pass independently. Wheel/sdist inventory and integrity
checks pass; four selected source/wheel/sdist/installed members match, with two
isolated installed imports and the fixed four-pin/nine-input inventory verified.
No readiness, launch, provider or Run authority is granted.
