# Minimal urllib3 native and quality lock advisory repair

Exact diagnosis base: PR 296 at 6dd4cab4efc19a8b6533ce4c884f242074a9ec7b.
Completed scan job 109846662760 / run 36703028724 rejects native urllib3 2.7.0
for CVE-2026-97687/97688/97689, fixed in 2.8.0. This is separate from the pending
Next.js carry.

Only the urllib3 version and wheel/source SHA-256 values change in the native
and quality locks. Official PyPI metadata and the prescribed pip-tools 7.6.0
compiler on Python 3.13 independently agree on both hashes. All other versions,
hashes, direct inputs, platform helpers, native build tools and workflow gates
remain unchanged. Python >=3.10 and Requests' existing urllib3 <3 constraint
admit the patch.

Primary upstream advisories identify 2.8.0 as patched:
https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77
https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g
https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw

Completed qualification: Linux 3.13 hash-checked quality installation; exact
strict native and quality audits report no known vulnerabilities; complete
native hash-checked no-install resolution passes on Linux and Windows 3.11;
all 12 repository dependency/workflow contracts pass in 0.176 seconds.

The initial Windows 3.11 audit-tool install exposed preexisting conditional
Colorama/typing-extension omissions in the Linux-generated quality lock. No
repository graph was changed to mask that; qualification matches actual CI's
Linux 3.13 platform. Native Windows resolution is independently verified.

Two independent reviews remain required. No owner/provider runtime, credential
or service changes. External Hermes image/package safety remains a separate
gate. Hosted acceptance is unverified; publication must preserve the pending
exact-head Next proposal before a later selective native repair.

Both independent lock/security reviews are clear. Reviewer B independently ran
10 dependency/CI contracts in 4.477 seconds. Source scope and all tested inputs
remain unchanged. The correction is committed locally only; no target branch
or pending bulk-security proposal is changed by this review record.
