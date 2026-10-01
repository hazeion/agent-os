# PR299 reviewed CI repair after security publication

Exact current security base: `38a3324f8390c756b9b72cf0cf030fbb2ec75bb0`. Target branch: `codex/ci-fixture-determinism`.
Original qualified source base: `f699b1199ac9ec8eedcda8863ed0d2f62f976611`. Reviewed local repair: `dbca1d8fe280dfc49e961d0fddf7608386992038`.
The independently reviewed webhook-root isolation from `83112e9314cb263eccf29e5129896449864ca7f2` is included separately.

Every changed file preimage is byte-identical to the qualified original source
base; all restored results are exact previously reviewed Git blobs. Relevant
database/private backup/registry test boundaries remain identical as applicable.
The newly published web package security files are preserved byte-for-byte.
No workflow, deadline, existing assertion, live root, provider or owner authority
is changed by this compatibility carry.

Copied prior review records and timings are historical qualification evidence,
not new hosted acceptance or speed claims. Current focused validation and two
exact-tree compatibility reviews are recorded in the ignored handoff before
publication. Hosted results remain unverified; no PR merge is performed.
