# PR 245 dependency advisory carry

Exact original product head: 0d5a11a9b3146ed0d449d5258f4da3192a68d81e.
Immediate prepared parent: 0d5a11a9b3146ed0d449d5258f4da3192a68d81e.

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
