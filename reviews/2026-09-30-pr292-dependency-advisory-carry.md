# PR 292 dependency advisory carry

Exact original product head: 089b549cf823106bb5e9047bb228e643245c6aee.
Immediate prepared parent: 089b549cf823106bb5e9047bb228e643245c6aee.

This carry changes only the dependency manifest and lock to the byte-identical,
independently reviewed PR 281 result e5c85aadede5a942e758c9cd8d533bc0628ff662. Next and eslint-config-next
pin 16.3.6 with matching Next env/plugin/SWC packages. The existing brace-expansion
1.1.21 / 5.0.12 and Undici 8.10.2 patches are retained or supplied when absent.
The package-key graph, other versions and Node 24 engine requirement remain
unchanged. No app, authority, schema, workflow, security gate or deadline changes.

The official Next advisory GHSA-vcvr-r3jv-pc5j identifies 16.3.6 as patched:
https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j
The dependency inventory does not prove application exploitability.

Historical reference qualification: PR 281 frozen install and audit report zero
vulnerabilities; lint/typecheck, all 489 web tests, production build and 65
private-bridge/disposable built-browser checks pass. The earlier PR 243 surface
also passes frozen install/audit, 369 web tests and production build with these
same package bytes. These are local representative results, not this head's
hosted acceptance. Exact-base compatibility and two independent carry reviews
are required before publication; hosted checks remain unverified until complete.
