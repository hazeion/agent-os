# PR 243 dependency advisory repair

Exact base: 24f8f6d0403661c5f8ff5a2b4d841ba5af8672c7.

Only web/package.json and web/package-lock.json change, to the byte-identical
reviewed PR 281 result e5c85aadede5a942e758c9cd8d533bc0628ff662.
Next and eslint-config-next pin 16.3.6, with matching env/plugin/SWC artifacts.
The previously reviewed dev-transitive brace-expansion 1.1.21 / 5.0.12 and
Undici 8.10.2 pins resolve the older audit failures. Package-key graph, unrelated
versions, Node engine requirement, app, authority and workflow gates remain
unchanged. Dependency presence is not proof of application exploitability.

Official advisory and patched version:
https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j

Fresh local qualification: frozen npm ci --ignore-scripts and npm audit report
zero vulnerabilities; lint/typecheck and all 369 web tests pass (42.301 seconds);
production build passes; all 62 private bridge/preview tests pass (30.385 seconds).
Both independent exact-base and package-byte reviews are clear. No owner
runtime, provider or service was used. Current-head hosted checks remain pending;
earlier green audits and any proposed approval of the prior SHA are historical.
No GitHub merge is performed.
