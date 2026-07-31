# Feature Slice Review: Apple Local Signing Proof

Status: Successful
Slice: `apple-local-signing-proof`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-apple-local-signing-proof.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  implementation, verification, publication, and continuation decisions.
- Standing approval covers this contract, test strategy, ephemeral signing
  operations, outcome, staging, commit, push, and ready pull request.
- The user confirmed that the certificate-bundle password is saved in their
  password manager, so a later notary-credential step may safely replace the
  macOS clipboard contents.

## Slice contract

### Goal

Prove on the maintainer Mac that Mentat's current `main` revision can be built
and signed with the newly created Developer ID Application and Developer ID
Installer identities before adding the remaining notarization credentials.
The tested revision is `8917ddc0ed6311dba3989e15bac9c440dfbbbe9a`.

### In scope

- Import the existing encrypted combined PKCS#12 bundle into a new temporary,
  private keychain without printing either password.
- Build the native Intel macOS application and unsigned installer from current
  `main` using the pinned native dependency set.
- Reproduce the protected workflow's signing order: nested Mach-O files,
  `Mentat.app`, and the final `.pkg`.
- Verify the exact app and package signatures, hardened runtime, expected Team
  ID, certificate authorities, package contents, and direct bundle health.
- Record whether Gatekeeper correctly withholds acceptance before notarization.
- Remove the temporary keychain and every local proof artifact afterward.

### Out of scope

- Apple notarization, stapling, or claiming public distribution readiness.
- Creating or storing the app-specific Apple password or changing the
  clipboard before the user confirms the bundle password is saved.
- Installing into `/Applications`, altering operator data, creating a release
  tag, or publishing an installer artifact.
- Windows/Azure signing and changes to the protected release workflow.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The bundle imports both expected Developer ID identities into a private temporary keychain without exposing secrets. | Keychain identity inventory and cleanup checks | Pass |
| AC-2 | Current `main` produces the expected Intel `Mentat.app` and unsigned package from the pinned build environment. | Build command, artifact inventory, architecture inspection | Pass |
| AC-3 | Every nested Mach-O, the app bundle, and final package are signed with the expected Team ID and hardened-runtime workflow. | `codesign` and `pkgutil` verification | Pass |
| AC-4 | The signed bundle starts against an isolated temporary data directory and answers its loopback health endpoint, then stops cleanly. | Direct bundle smoke | Pass |
| AC-5 | Gatekeeper behavior is recorded honestly before notarization and all proof-created temporary signing material/artifacts are removed. | `spctl` result and post-cleanup inventory | Pass |
| AC-6 | Two independent adversarial reviewers find no unresolved blocking gap in the proof or evidence. | Review record | Pass |

### Constraints and recovery

- Safety: never echo passwords, certificate bytes, private keys, keychain
  passwords, or local private paths into the tracked record.
- Compatibility: use the same signing order and exact identity classes as the
  protected workflow; do not mutate that workflow in this slice.
- Rendered behavior: not applicable; this is a packaging/signing proof.
- Rollback or recovery: delete the temporary keychain and temporary artifact
  directory; the repository and installed applications remain unchanged.
- Documentation targets: this review log only unless verification exposes a
  repository-owned signing defect.
- Version-control strategy: branch `codex/apple-local-signing-proof` from
  merged `main`; ready PR to `main` containing only the evidence record.

### Scope discussion and approval

- Recommendation and rationale: validate the two Developer ID identities and
  the exact local signing path now, isolating certificate/build failures from
  the later notary-service and Windows gates.
- Alternatives considered: wait for all credentials before testing (combines
  unrelated failure modes); dispatch the full workflow now (must fail because
  two Apple secrets and all Azure variables are absent); install the
  unnotarized package (unnecessary system mutation).
- User decisions: standing approval for all slices and related actions.
- Approved at: `2026-07-31` under the recorded process exception.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The combined bundle round-tripped earlier, but has not signed a Mentat build. | Import into an owner-only temporary keychain and list matching identities by class. | Both private-key identities are usable by Apple signing tools. | Does not contact the notary service. |
| AC-2 | Hosted unsigned packaging is green; this exact maintainer environment has not built the candidate. | Install/use pinned native dependencies, build to an isolated directory, inspect Mach-O architecture and bounded contents. | Current source and local toolchain produce the intended Intel bundle. | Proves this Mac only. |
| AC-3 | Workflow contract tests cannot prove the new certificates work. | Sign nested binaries/app/package with timestamping; run strict signature and package checks; inspect authority/team/runtime metadata. | The new identities work with the real artifact hierarchy. | Timestamp receipt is not notarization. |
| AC-4 | Signature validity alone does not prove the frozen launcher works. | Start the signed bundle on an isolated port/data root, poll `/api/health`, stop, and verify shutdown/data initialization. | The signed bundle remains executable and functional. | Does not exercise GUI installation. |
| AC-5 | An unnotarized Developer ID build should not be claimed as Gatekeeper-ready. | Run app/package assessments, record expected rejection, then verify keychain/artifact removal. | The proof distinguishes signing from notarization and leaves no proof-created residue. | Gatekeeper result becomes acceptance only after notarization/stapling. |
| AC-6 | Operational evidence can omit critical identity or cleanup details. | Two independent read-only adversarial reviews of the log and repository contract. | Correctness, safety, compatibility, and evidence adequacy receive independent scrutiny. | Reviewers do not access secrets. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short --branch` | macOS, merged `main` | Pass | Only user-owned `data/projects.json` and `design/` are outside the slice. |
| Protected environment secret-name inventory | GitHub `beta-release` | Expected gap | Five Apple secrets exist; `MAC_NOTARY_APPLE_ID` and `MAC_NOTARY_PASSWORD` are absent. No Azure variables exist. Values were not read. |
| Signing bundle metadata inspection | macOS private temporary storage | Pass | Encrypted bundle and password file exist with owner-only permissions; contents were not printed. |
| Protected workflow inspection | `.github/workflows/signed-release-artifacts.yml` | Trust-chain gap found | Signing, verification, notarization, stapling, Gatekeeper, and exact-package smoke steps are structurally fail-closed, but the isolated signing keychain cannot establish the actual bundle's G2 trust chain. Hosted macOS signing/notarization must not be dispatched until the separate workflow fix merges. |

### Test discussion and approval

- User questions and decisions: standing approval applies; clipboard remains
  untouched until the user confirms the password is saved.
- Accepted coverage gaps: notarization, installation, Apple Silicon/Rosetta,
  Windows signing, and the clean-machine rehearsal remain later external gates.
- Approved at: `2026-07-31` under the recorded process exception.

## Implementation record

### Changes

- Created a disposable, hash-locked Python build environment in private
  temporary storage because the system Python did not include PyInstaller.
- Imported the combined encrypted PKCS#12 signing bundle without printing its
  password or contents. The import contained two certificates and two private
  keys for the expected Application and Installer identity classes.
- Downloaded Apple's public Developer ID G2 intermediate directly from the
  Apple Certificate Authority service and verified its pinned SHA-256 digest:
  `F16CD3C54C7F83CEA4BF1A3E6A0819C8AAA8E4A1528FD144715F350643D2DF3A`.
- Built the pinned Intel application, signed 85 nested Mach-O files, signed the
  application with hardened runtime and a trusted timestamp, then signed the
  final installer package.
- Ran strict app/package signature inspection, payload inspection, a direct
  isolated bundle smoke, honest pre-notarization Gatekeeper assessment, and
  cleanup verification.
- No repository source or workflow file changed in this evidence-only slice.

### Deviations and decisions

- The first import produced zero trusted identities because the maintainer Mac
  did not yet have Apple's newer Developer ID G2 intermediate. Importing that
  public intermediate into the isolated keychain alone still produced
  `CSSMERR_TP_NOT_TRUSTED` and signing failed with `errSecInternalComponent`.
- Certificate-chain verification independently proved the leaf, official G2
  intermediate, and system Apple Root CA form a valid public chain.
- The minimum working macOS configuration was a private temporary keychain for
  the private identities, a temporary import of the official public G2
  intermediate into the login keychain, and a signing search list containing
  both keychains. The original search list was captured and restored, and the
  public intermediate was removed from the login keychain after the proof.
- This exposes a repository-owned follow-up: the protected workflow currently
  searches only its temporary keychain and does not acquire the official G2
  intermediate. The workflow must be corrected in a separate reviewed code
  slice before hosted signing is treated as viable. Mutating that workflow was
  intentionally outside this evidence-only contract.
- The protected workflow also deletes its temporary keychain without restoring
  the user keychain search list that it replaced. Hosted runners are ephemeral,
  but the G2 correction must preserve and restore the original list in its
  always-run cleanup rather than leave invalid keychain state behind.

## Verification

### Focused checks

- Environment: x86_64 Mac, macOS 15.7.7, Python 3.13.14, and
  `notarytool 1.0.0 (38)`.
- Identity inventory: two trusted Developer ID identities were available after
  establishing the official public chain, one Application and one Installer,
  both for Team ID `VLWLW82PZ7`.
- Build architecture: the application executable is a 64-bit x86_64 Mach-O.
- Nested signing: 85 Mach-O files signed with the Developer ID Application
  identity.
- Application verification: `codesign --verify --deep --strict` passed. The
  inspected code directory had hardened-runtime flag `0x10000`, the expected
  Team ID, a trusted timestamp, and the Developer ID Application -> Developer
  ID Certification Authority -> Apple Root CA chain.
- Package verification: `pkgutil --check-signature` reported an Apple-issued
  Developer ID Installer signature and trusted timestamp. Payload inspection
  found the exact `Applications/Mentat.app/Contents/MacOS/Mentat` executable.
- Direct bundle smoke: launched on loopback port 8896 with an isolated data
  directory, passed `/api/health`, initialized isolated task data, stopped the
  exact process, cleared runtime state, and left the health endpoint offline.
- Gatekeeper assessment: both app and package were rejected with
  `source=Unnotarized Developer ID`, the correct pre-notarization result.
- Cleanup: restored the original user keychain search list, removed the public
  G2 intermediate from the login keychain, deleted the temporary keychain,
  build/proof directory, and proof script, and verified no listener remained
  on port 8896. The encrypted source signing bundle remains intentionally until
  the first hosted macOS signing succeeds.

#### Sanitized execution evidence

The proof ran as one fail-fast local script. The table preserves the relevant
command shapes, bounded public output, and exit semantics without private paths,
passwords, private-key bytes, or certificate-bundle contents.

| Check | Sanitized command or operation | Bounded result | Exit |
| --- | --- | --- | --- |
| Bundle import | `security import <bundle> -x -k <temporary-keychain> -P <password> -T /usr/bin/codesign -T /usr/bin/pkgbuild` | Two certificates and two private keys imported; no trusted identity until the public G2 chain was available. | `0` |
| G2 authenticity | `curl --fail --location --silent --show-error <official-Apple-G2-URL>` then `shasum -a 256 <G2-certificate>` | SHA-256 matched `F16CD3C54C7F83CEA4BF1A3E6A0819C8AAA8E4A1528FD144715F350643D2DF3A`. | `0` |
| Public chain | `security verify-cert -c <application-leaf> -c <G2-intermediate> -r <Apple-root>` | Leaf -> Developer ID Certification Authority G2 -> Apple Root CA verified. | `0` |
| Identity inventory | `security find-identity -v -p codesigning <temporary-keychain>` plus certificate/private-key inventory and the later signed-package verification | The codesigning policy resolved the expected Application identity; certificate/private-key matching identified the expected Installer identity for Team ID `VLWLW82PZ7`, and successful `pkgbuild`/`pkgutil` checks proved its use. | `0` |
| Pinned build | Run `python scripts/build_native.py` from a private copy of tested revision `8917ddc0ed6311dba3989e15bac9c440dfbbbe9a`, using a disposable environment installed with `--require-hashes -r requirements-native.lock`. | Produced Intel `Mentat.app` and unsigned installer inputs. | `0` |
| Architecture | `file <Mentat-executable>` | `Mach-O 64-bit executable x86_64`. | `0` |
| Nested signing | Discover Mach-O files with `file`, then `codesign --force --options runtime --timestamp --sign <application-identity> <file>` | 85 nested Mach-O files signed. | `0` |
| App signing | `codesign --force --options runtime --timestamp --sign <application-identity> <Mentat.app>` | Developer ID Application signature created with hardened runtime and timestamp after the 85 nested Mach-O files were signed individually; `--deep` was used only by the subsequent verification command. | `0` |
| App verification | `codesign --verify --deep --strict --verbose=2 <Mentat.app>` and `codesign --display --verbose=4 <Mentat.app>` | Strict verification passed; flags `0x10000(runtime)`, expected Team ID, Application -> G2 -> Apple Root chain. | `0` |
| Package signing | Rebuild the package root and run `pkgbuild --root <package-root> --component-plist <plist> --install-location / --identifier dev.mentat.local --version <version> --sign <installer-identity> <signed.pkg>`. | `Mentat-0.1.0-beta.1-macos-x86_64-signed.pkg` produced. | `0` |
| Package verification | `pkgutil --check-signature <signed.pkg>` | Apple-issued Developer ID Installer signature, trusted timestamp, Installer -> G2 -> Apple Root chain. | `0` |
| Payload inspection | `pkgutil --payload-files <signed.pkg>` | Included exact `./Applications/Mentat.app/Contents/MacOS/Mentat`. | `0` |
| Direct smoke | Start signed executable with isolated loopback port/data root; request `/api/health`; invoke exact lifecycle stop; re-request health | Health passed, isolated data initialized, exact process stopped, runtime state cleared, endpoint unavailable afterward. | `0` |
| App Gatekeeper | `spctl --assess --type execute --verbose=4 <Mentat.app>` | Expected rejection: `source=Unnotarized Developer ID`. | `3` (expected) |
| Package Gatekeeper | `spctl --assess --type install --verbose=4 <signed.pkg>` | Expected rejection: `source=Unnotarized Developer ID`. | `3` (expected) |
| Cleanup | Restore captured keychain list; delete temporary public G2 login certificate and temporary keychain; remove proof artifacts; probe port 8896 | User search list contained only the original login keychain; temporary certificate/keychain/artifacts absent; port not listening. | `0` |

The script's final summary was
`identities=2 macho=85 architecture=x86_64 app_signature=valid package_signature=valid smoke=pass app_gatekeeper_exit=3 package_gatekeeper_exit=3`,
and the script itself exited `0` only after cleanup checks passed.

### Full suite

- Repository code is unchanged in this operational slice; the exact merged
  revision already passed all 50 required GitHub checks on pull request 80.

### Rendered or manual behavior

- Not applicable.

## Adversarial review

- Correctness and safety review initially raised one P1 because the evidence
  summarized ephemeral checks without preserving sanitized commands and exit
  semantics, plus a P2 for restoring the keychain search list in the future
  workflow fix. The command/evidence table and follow-up scope resolved both.
- That reviewer then caught a P1 transcription error showing `--deep` on the
  app-signing command. The record was corrected to match the actual proof and
  protected workflow: sign nested Mach-O files first, sign the outer app
  without `--deep`, and use `--deep` only for verification. Installer identity
  evidence was also clarified. Final re-review found no P0 or P1 findings.
- Compatibility and operability review raised no P0/P1 findings. Its P2/P3
  wording requests were resolved by classifying the workflow baseline as a
  trust-chain gap, pinning the full tested revision and script exit, narrowing
  cleanup claims to proof-created residue, and making the G2/search-list repair
  the immediate next slice while preserving the dual-platform release gate.
  Final re-review found no P0-P3 concerns.
- Both independent reviewers agreed the discovered hosted-workflow defect does
  not invalidate this evidence-only local proof and that the slice can be
  classified Successful.

## Documentation updates

- Roadmap: no status claim until the proof finishes.
- Changelog: not applicable unless repository behavior changes.
- Architecture/operator docs: no change planned.
- Project/session notes: this review log.
- Documentation verification: this tracked review record contains no private
  key material, passwords, local certificate paths, or certificate bytes.

## Publication gate

- Contract, strategy, AC-1 through AC-6, focused evidence, cleanup, and both
  independent reviews pass. Publication is authorized under the standing
  approval and will include only this review record, excluding user-owned data
  and designs.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-6 pass.
- Potential bugs or untested paths: notarization and clean-machine installation
  intentionally remain outside this slice. Hosted macOS signing is also blocked
  by the demonstrated G2/search-list defect until the next reviewed code slice
  fixes the workflow and its structural tests/operator documentation.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no migration; cleanup required.
- User decision: standing approval recorded; Successful outcome accepted under
  the process exception.
- Next slice authorized: Yes, under the standing process exception, after this
  slice is complete and published. The immediate next slice is the protected
  workflow G2 trust-chain/search-list correction; the dual-platform release and
  tag gate must remain intact while Azure is deferred.
