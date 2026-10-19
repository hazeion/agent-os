# Qualification comparison package data

Status: local real artifact verification complete; independent review pending.

This additive packaging slice follows the fixed dependency comparison and its
independently reviewed audit cleanup/advisory follow-ups. Include only the exact
public dependency candidate JSON alongside the existing origin lock in wheel
and sdist inventories. Preserve every original public file, private-data
exclusion, integrity check, scanner detector and threshold. The candidate remains
non-production; shipping its public manifest grants no runtime readiness,
constraint exception, provider consent or execution authority.

Tests will require the explicit package-data and source-manifest entries and
both exact artifact inventories. Real wheel/sdist construction and strict
verification will use an actual portable standalone web runtime if available;
an inert JavaScript fixture will not be presented as full runtime packaging
evidence. Compare the packaged manifest and loader bytes with source and prove
installed lookup works without selecting the baseline differently.

The secret baseline update will preserve existing fingerprints and occurrence
counts, add only actual new reviewed findings from the dependency slice, and
identify them as public immutable artifact or source identities. No credentials,
new detector exclusion, wildcard allowlist or synthetic safety receipt is added.

The selected scan finds exactly eighteen new public-hash occurrences: thirteen
in the candidate document (the baseline identity plus twelve wheel digests) and
five in the dependency tool (candidate identity, PyJWT wheel identity, fix/release
Git commits and the exact released source-member Git blob). Every value binds a
public artifact or source, not authentication material. The update retains every
prior filename/type/fingerprint occurrence count and leaves all detector, filter
and other baseline metadata unchanged. The synthetic environment-key test already
has its own narrow inert-fixture annotation; no additional bypass is introduced.

Packaging code adds one explicit candidate resource to package-data, one source
manifest entry and the exact source/wheel verifier inventories. All other source
and wheel membership remains governed by the existing exact inventories and
RECORD verification. The original packaging tests remain byte-identical. A
proposed config-mirroring test was removed in review; actual artifact inventory,
integrity, installed lookup and missing-member refusal provide stronger evidence.

## Local artifact verification

The final dependency branch, including owned-audit-group cleanup and exact
PyJWT released-member evidence, was merged normally before this packaging
change. The dependency source and fixed candidate document remain unchanged
in this slice. The original packaging test file is byte-identical to that parent.

The actual built Next standalone runtime came from the completed owner-website
acceptance build. Its source commit `826d243` has no differences in `web/` or
`.node-version` against dependency tip `f5845c4`; its working tree was clean.
Only read/copy operations touched that checkout. The regular-file/native-payload
validator and normal staging command checked the copied runtime in a separate
scratch source tree. No inert server.js or synthetic runtime was substituted.
These are current Mac-build packaging checks, not Linux execution qualification.

With Python 3.13, build 1.3.0, setuptools 83.0.0 and wheel 0.47.0:

- All sixteen unchanged `PackagingContractTests` pass without skips.
- Normal `python -m build --no-isolation` constructs a real sdist and the wheel
  from that sdist. Existing `scripts/verify_python_artifacts.py` accepts both
  exact public inventories and the complete wheel RECORD integrity graph.
- Candidate JSON bytes match source in both archives; the wheel loader module
  also matches source exactly. The original origin-lock bytes remain unchanged.
- Removing the candidate from a copied wheel fails exact membership; changing
  its bytes fails RECORD integrity. Removing it from a copied sdist also fails
  exact membership. No verifier threshold or check is disabled for these probes.
- Installing the real wheel with no dependency installation into a fresh scratch
  target, then importing with `-I -S -B`, loads the installed manifest and loader.
  Both match source bytes, return the fixed 111-package/twelve-replacement
  comparison and preserve the original source/Python/baseline selections.
- The full unchanged tracked-secret gate passes after the eighteen explicit
  public-hash additions. All prior fingerprint occurrence counts and non-results
  metadata remain exact. Source parsing and whitespace checks pass.

Built artifacts retained only in disposable scratch storage:

| Artifact | SHA256 |
| --- | --- |
| `mentat_local-0.1.0b1-py3-none-any.whl` | `9b962a7d3c538659a734d46c09dd0e6baecd2f42492a773010d7c6f16738b978` |
| `mentat_local-0.1.0b1.tar.gz` | `c3acee105d2fa12c60e91ddf680a4569100f0267f902c8456862ee9a7992d4d0` |

The candidate remains a public non-production comparison. Its unchanged official
Hermes PyJWT requirement still blocks stage materialization; packaging does not
approve a dependency override, provider, account, runtime or Run. Actual Linux,
host/helper, provider and end-to-end acceptance remain separate. No generated
artifact, private state, owner configuration, push or PR is included in this slice.
