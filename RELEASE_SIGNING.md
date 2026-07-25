# Release signing setup

This is the one-time maintainer setup for Mentat release candidates. Keep every
credential in the protected GitHub `beta-release` environment. Never commit,
upload, or paste signing material into an issue, pull request, or chat.

## What you need

- An active Apple Developer Program membership with the Account Holder role.
- An Azure subscription and Microsoft Entra tenant eligible for public
  [Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/quickstart).
- Admin access to the `hazeion/agent-os` GitHub repository.

The protected workflow uses an Apple Developer ID identity for macOS and Azure
Artifact Signing for Windows. Windows authentication is passwordless: GitHub
requests a short-lived Azure token through OpenID Connect (OIDC), and the
Windows private key never enters GitHub.

## 1. Prepare Apple signing

1. In **Keychain Access**, create a certificate signing request.
2. In Apple Developer
   [Certificates](https://developer.apple.com/account/resources/certificates/list),
   create both:
   - **Developer ID Application** — signs `Mentat.app`;
   - **Developer ID Installer** — signs the `.pkg`.
3. Download and open both certificates so they appear under **My
   Certificates** with their private keys.
4. Select only those two identities in Keychain Access and export them together
   as a password-protected `mentat-signing.p12`.
5. Generate an
   [app-specific Apple password](https://support.apple.com/102654) for
   notarization. Do not use the normal Apple Account password.
6. Copy the 10-character Team ID from the Apple Developer membership page.

Apple's
[Developer ID guide](https://developer.apple.com/help/account/certificates/create-developer-id-certificates)
has the certificate creation details. The workflow submits with `notarytool`,
waits for Apple, staples the ticket, and verifies the result.

Add these seven **environment secrets** under **Repository settings →
Environments → beta-release**:

| Secret | Value |
| --- | --- |
| `MAC_CERTIFICATES_BASE64` | Base64 of `mentat-signing.p12`, with no line breaks |
| `MAC_CERTIFICATES_PASSWORD` | Password chosen while exporting the `.p12` |
| `MAC_APPLICATION_IDENTITY` | Full `Developer ID Application: …` identity |
| `MAC_INSTALLER_IDENTITY` | Full `Developer ID Installer: …` identity |
| `MAC_NOTARY_APPLE_ID` | Apple Account email used for notarization |
| `MAC_NOTARY_PASSWORD` | App-specific password |
| `MAC_NOTARY_TEAM_ID` | Apple Developer Team ID |

On macOS, this copies the encoded certificate to the clipboard without writing
another file:

```bash
base64 -i mentat-signing.p12 | tr -d '\n' | pbcopy
```

Delete the exported `.p12` after the GitHub secret is saved and verified. The
workflow creates its temporary keychain with a fresh random password for each
run.

## 2. Prepare Windows signing

1. Follow Microsoft's
   [Artifact Signing quickstart](https://learn.microsoft.com/azure/artifact-signing/quickstart)
   to create:
   - an Artifact Signing account;
   - a completed public-trust identity validation;
   - a public-trust certificate profile.
2. Create a Microsoft Entra application or user-assigned managed identity for
   the GitHub workflow. If using an app registration, confirm its service
   principal exists in the tenant.
3. Add a federated credential. In the Azure portal, choose the **GitHub actions
   deploying Azure resources** scenario and enter:
   - Organization: `hazeion`
   - Repository: `agent-os`
   - Entity type: **Environment**
   - Environment: `beta-release`

   If the portal asks for the claims directly, use these exact values:

   | Claim | Value |
   | --- | --- |
   | Issuer | `https://token.actions.githubusercontent.com` |
   | Subject | `repo:hazeion/agent-os:environment:beta-release` |
   | Audience | `api://AzureADTokenExchange` |

4. Give that identity the **Artifact Signing Certificate Profile Signer** role
   on the certificate profile.
5. Do not create a client secret. The workflow has only `id-token: write` and
   uses GitHub OIDC through the pinned Azure Login action.

Add these six **environment variables**—not secrets—to `beta-release`:

| Variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | Entra application or managed identity client ID |
| `AZURE_TENANT_ID` | Microsoft Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `AZURE_ARTIFACT_SIGNING_ENDPOINT` | Regional endpoint, such as `https://eus.codesigning.azure.net/` |
| `AZURE_ARTIFACT_SIGNING_ACCOUNT` | Artifact Signing account name |
| `AZURE_ARTIFACT_SIGNING_PROFILE` | Public-trust certificate profile name |

Microsoft's
[GitHub Action](https://github.com/Azure/artifact-signing-action) signs both
Mentat executables before packaging, then signs the final installer. The
workflow verifies every Authenticode signature with SignTool before upload.
Microsoft's
[GitHub OIDC guide](https://learn.microsoft.com/azure/developer/github/connect-from-azure)
explains the Entra federation flow.

## 3. Check GitHub protections

Before the first candidate, confirm:

- the `main` ruleset requires pull requests and the stable checks;
- `beta-release` requires a reviewer and uses **Selected branches and tags**
  with exactly one allowed branch: `main`;
- the `v0.1.0-beta.*` tag ruleset blocks tag updates, deletion, and force
  pushes;
- the environment contains exactly the seven Apple secrets and six Azure
  variables above.

Environment secrets are released to a job only after its protection rules pass.
GitHub documents that behavior in
[Deployments and environments](https://docs.github.com/actions/reference/workflows-and-actions/deployments-and-environments).

## 4. Create the first candidate

From **Actions → Signed beta artifacts**, choose **Run workflow** on `main` and
enter:

```text
v0.1.0-beta.1-rc.1
```

Approve the waiting `beta-release` jobs only after confirming the exact source
commit. A successful run creates the immutable prerelease and recovery bundle.
Then use [RELEASE_REHEARSAL.md](RELEASE_REHEARSAL.md) to test those exact
files.

If any signing or notarization step fails, do not publish replacement files
under the same tag. Fix the configuration and issue the next RC number.
