# Google identity verifier

Scope: [Strict Google identity verification and authorization requests](https://github.com/hazeion/agent-os/issues/246),
under the approved owner-login roadmap. Baseline: `6893408`.

This component grants no owner/session authority and exposes no route. It can
be verified independently while baseline CI runs. Migration, one-use durable
transactions, fixed-host exchange, CLI enrollment/recovery, authenticated
gateway and actual provider acceptance remain required parent work.

## Contract and sources

Use pinned google-auth signature verification with RS256 only and an externally
supplied bounded Google JWKS snapshot from future fixed-host transport. Reject
duplicate JSON keys, attacker-selected JOSE key URLs/algorithms, unknown keys,
oversized input and malformed claim types before trust. Require exact audience,
authorized party when present, accepted Google issuer, future-safe issued time,
strict expiry, and the exact server-held nonce. Return only private issuer,
subject and bounded verified-email evidence; email is never owner identity.

Build only a fixed Google authorization-code request with openid/email scopes,
S256 challenge, state, nonce and the fixed same-origin callback. No implicit flow,
offline access, Calendar permission or arbitrary return URL.

Primary sources checked September 21:
- https://developers.google.com/identity/openid-connect/openid-connect
- https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html
- https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation
- https://www.rfc-editor.org/rfc/rfc9700.html

Google documents both boolean-style verification semantics and a string "true"
in its signed-token example; accept only boolean true or that exact string for
verified-email display. Never infer freshness/MFA from optional auth_time/amr.

## Validation plan

Use ephemeral RSA keys and actual signatures. Cover key/algorithm confusion,
wrong claims, exact expiration, duplicates and size/depth limits, missing/multiple
key IDs, minimal output, no raw error leakage, fixed URL scopes/PKCE and artifact
inventory. Two independent read-only adversarial reviews before publication.

## Evidence

Implemented the isolated component and package inventory. Ten verifier test
methods cover actual ephemeral signatures and adversarial subcases. Both
independent security reviewers found no actionable concerns and each reran the
verifier suite successfully.

Final verification in an isolated Python 3.13 environment installed from the
hash-locked native requirements: 61 verifier, existing owner-auth, packaging and
quality-contract tests passed. The wheel and sdist built and passed exact
inventory/RECORD validation. Installed-wheel import passed with isolated Python
module lookup. A Windows path-normalized tracked-secret diagnostic found no new
candidates; the ordinary Linux CI scan remains required.

No live Google calls, owner enrollment, database migration, browser routes or
login-readiness claim. The dependent authority/transport work remains open.
