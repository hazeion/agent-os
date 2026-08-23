# Help Test Mentat

Thanks for helping! The limited beta is for checking that Mentat is easy to
install, useful in real work, and safe to recover when something goes wrong.

Only start with the exact Mentat release candidate and verified Hermes build
your invitation links to. The invitation also gives you the right local or
remote Hermes connection steps; credentials are shared privately, never in
GitHub.
Plan to use Mentat for about two weeks. You should not need to share private
project data.

## Before you begin

- Use a supported macOS or Windows computer. Linux is welcome as a preview.
- Install Node 24.19 or newer within Node 24 before launching Mentat. Native
  installers include the prebuilt dashboard but use this local Node runtime.
- Finish the invitation's Hermes setup before timing the Mentat install.
- Keep the release link and version from your invitation.
- Never post credentials, private conversations, note contents, or personal
  files in an issue. Keep endpoints, hostnames, IP addresses, and private
  network details out too.

## First launch

Read the matching path now, but wait for checklist step 1 to start your timer.
Use only the exact release candidate linked by your invitation. Download its
`SHA256SUMS` file with your assigned artifact, confirm that the artifact's
SHA-256 value matches its line, and stop if it does not. **Do not install it**
after a checksum mismatch; report that as an install blocker.

Choose the one install channel assigned by your invitation:

### macOS native

Apple Silicon is the recommended/default Mac path. Download the package that
matches the Mac, plus `SHA256SUMS`, into Downloads:

- Apple Silicon: `Mentat-0.1.0-beta.1-macos-arm64-signed.pkg`
- Intel: `Mentat-0.1.0-beta.1-macos-x86_64-signed.pkg`

In Terminal, run the matching command and compare the printed value with the
package's line in `SHA256SUMS`.

   ```text
   shasum -a 256 "$HOME/Downloads/Mentat-0.1.0-beta.1-macos-arm64-signed.pkg"
   shasum -a 256 "$HOME/Downloads/Mentat-0.1.0-beta.1-macos-x86_64-signed.pkg"
   ```

Open the matching `.pkg` from Downloads and finish the installer. Then select
**Open Mentat from Applications**. The Node dashboard should open in your
browser. Use `mentat start --legacy-ui` only if support asks you to test the
temporary rollback interface.

### Windows native

1. Download `Mentat-0.1.0-beta.1-windows-x64.exe` and `SHA256SUMS` into
   Downloads.
2. In PowerShell, run the command below. Compare the printed value with the
   installer's line in `SHA256SUMS`.

   ```text
   Get-FileHash "$env:USERPROFILE\Downloads\Mentat-0.1.0-beta.1-windows-x64.exe" -Algorithm SHA256
   ```

3. Run the installer from Downloads and keep the recommended choices.
4. Open Mentat from the Start menu. The Node dashboard should open in your
   browser. Use `mentat start --legacy-ui` only if support asks you to test the
   temporary rollback interface.

### pipx

This channel requires Python 3.11–3.13, Node 24.19 or newer within Node 24,
and `pipx`. Confirm they are installed before starting the timer. If `pipx` is
missing, use its [official installation guide](https://pipx.pypa.io/latest/how-to/install-pipx.html).

1. Download `mentat_local-0.1.0b1-py3-none-any.whl` and `SHA256SUMS` into
   Downloads.
2. Verify the wheel before installing it. On macOS, run:

   ```text
   shasum -a 256 "$HOME/Downloads/mentat_local-0.1.0b1-py3-none-any.whl"
   ```

   On Linux, run:

   ```text
   sha256sum "$HOME/Downloads/mentat_local-0.1.0b1-py3-none-any.whl"
   ```

   On Windows PowerShell, run:

   ```text
   Get-FileHash "$env:USERPROFILE\Downloads\mentat_local-0.1.0b1-py3-none-any.whl" -Algorithm SHA256
   ```

   Compare the printed value with the wheel's line in `SHA256SUMS`.
3. Install that verified local wheel. On macOS or Linux, run:

   ```text
   pipx install "$HOME/Downloads/mentat_local-0.1.0b1-py3-none-any.whl"
   ```

   On Windows PowerShell, run:

   ```text
   pipx install "$env:USERPROFILE\Downloads\mentat_local-0.1.0b1-py3-none-any.whl"
   ```

4. Finish setup and open Mentat:

   ```text
   mentat setup
   mentat start --open-browser
   ```

When Mentat opens, continue with the checklist below. Do not switch install
channels during the timed attempt unless your invitation asks you to.

## Your checklist

1. Start your timer, then follow the matching **First launch** path above
   without maintainer help. Note where you get stuck, even if you solve it.
2. Open **Settings → Help & Diagnostics** and confirm the expected Mentat
   version appears.
3. Complete a first useful workflow: create a project and task, then finish the
   assigned Hermes workflow. Stop the timer after that workflow succeeds.
4. If you are assigned remote Hermes checks, complete every row in the
   [versioned remote check guide](REMOTE_BETA_MATRIX.md) as `pass`,
   `pass-with-help`, `blocked`, or `not-run`. A row passes only when all of its
   listed actions and expected results pass.
5. Notice whether unavailable Calendar, Obsidian, or Hermes features explain
   themselves clearly.
6. Report an install or core-workflow blocker through the beta feedback form
   immediately—do not wait for the two-week window. Use the private advisory
   path below instead for security, unsafe changes, exposure, or data loss.
7. Use Mentat normally for about two weeks. Keep short notes about confusing
   steps, workarounds, and anything that blocks you.
8. If your invitation includes the migration or recovery drill, use disposable
   test data and follow the
   [backup and recovery checklist](RELEASE_REHEARSAL.md). Do not risk your only
   copy of important data.
9. Check [known beta issues](KNOWN_ISSUES.md), then send the
   [limited beta feedback form](https://github.com/hazeion/agent-os/issues/new?template=beta_feedback.yml).
   Helpful rough timings are better than perfect measurements.

If Mentat may have exposed data, changed something unsafe, or caused data loss,
stop using that build and open a
[private security advisory](https://github.com/hazeion/agent-os/security/advisories/new).
Do not describe a security problem in a public issue.

For setup boundaries and current limitations, see [Beta Support](SUPPORT.md).
