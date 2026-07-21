# Release rehearsal

This checklist proves a Mentat release candidate is safe to share. Use fresh
Intel and Apple Silicon Macs, a fresh Windows machine, and a clean Python
3.11–3.13 setup. The first macOS package is Intel; Apple Silicon testing uses
Rosetta.

## 1. Build the candidate

1. Confirm `main` is protected and CI, native artifacts, and quality gates pass.
2. Confirm the release-tag rule blocks tag updates and deletion.
3. Confirm the protected `beta-release` environment has the macOS and Windows
   signing credentials and an approver.
4. Write down the exact legacy-checkout commit and previous package tag used as
   upgrade baselines. For the first RC, use reviewed non-private fixture data.
5. Run **Signed beta artifacts** on `main` with the next tag, such as
   `v0.1.0-beta.1-rc.1`.
6. Download the four release files, `SHA256SUMS`, and
   `release-manifest.json`. Do not test a file from another build.
7. Verify every checksum. On macOS use `shasum -a 256 -c SHA256SUMS`; on
   Windows compare `Get-FileHash FILE -Algorithm SHA256` with `SHA256SUMS`.

Stop if a signature, notarization, checksum, or required workflow fails.

## 2. Run the install and recovery checks

Use these exact candidate filenames. Replace `TAG` only with the RC tag:

- `Mentat-0.1.0-beta.1-macos-x86_64-signed.pkg`
- `Mentat-0.1.0-beta.1-windows-x64.exe`
- `mentat_local-0.1.0b1-py3-none-any.whl`
- `mentat_local-0.1.0b1.tar.gz`

Use the Mentat command for the channel being tested:

| Channel | Mentat command |
| --- | --- |
| macOS native | `/Applications/Mentat.app/Contents/MacOS/Mentat` |
| Windows native | `& "$env:LOCALAPPDATA\Programs\Mentat\mentat.exe"` |
| pipx | `mentat` |

Install the exact candidate:

- macOS: `sudo installer -pkg ./Mentat-0.1.0-beta.1-macos-x86_64-signed.pkg -target /`
- Windows PowerShell: `Start-Process .\Mentat-0.1.0-beta.1-windows-x64.exe -Wait`
- pipx: `pipx install https://github.com/hazeion/agent-os/releases/download/TAG/mentat_local-0.1.0b1-py3-none-any.whl`

First prove a clean candidate install with a brand-new `--data-dir`. Start with
`COMMAND start --data-dir CLEAN_INSTALL_DIR --open-browser`, check the
dashboard, then run `COMMAND stop --data-dir CLEAN_INSTALL_DIR`.

Next, prove a real upgrade in a separate `UPGRADE_DIR`:

1. Install the recorded previous package—not the candidate—or start the
   recorded legacy checkout with reviewed, non-private fixture data.
2. Start that previous version with `--data-dir UPGRADE_DIR`, confirm the
   fixture data, then stop it with the same option.
3. Run `COMMAND backup --data-dir UPGRADE_DIR` **before** installing the
   candidate. Its JSON output contains a `backup_name`; the file is
   `UPGRADE_DIR/backups/BACKUP_NAME`. Copy it outside `UPGRADE_DIR`.
4. Install the candidate over the previous application. For pipx, use
   `pipx install --force https://github.com/hazeion/agent-os/releases/download/TAG/mentat_local-0.1.0b1-py3-none-any.whl`.
5. Start the candidate with `--data-dir UPGRADE_DIR` and compare the fixture
   data. For a legacy checkout, follow the preview/confirm migration commands
   in [DATA_LAYOUT.md](DATA_LAYOUT.md). Then stop the candidate with
   `--data-dir UPGRADE_DIR`.

For an ordinary default-data backup, the reported file lives here:

- macOS: `~/Library/Application Support/Mentat/backups/BACKUP_NAME`
- Windows PowerShell: `$env:LOCALAPPDATA\Mentat\backups\BACKUP_NAME`
- Linux preview: `~/.local/share/Mentat/backups/BACKUP_NAME`

For example, copy it away with `cp "$HOME/Library/Application Support/Mentat/backups/BACKUP_NAME" "$HOME/Desktop/"` on macOS or
`Copy-Item "$env:LOCALAPPDATA\Mentat\backups\BACKUP_NAME" "$HOME\Desktop\"`
in Windows PowerShell.

To prove a clean restore, choose a brand-new, empty `RESTORE_DIR`; do not move
or delete real operator data. Start and stop the candidate once with
`--data-dir RESTORE_DIR`, then run
`COMMAND restore PATH_TO_COPIED_BACKUP --data-dir RESTORE_DIR`. Review the
preview and repeat it as `COMMAND restore PATH_TO_COPIED_BACKUP --data-dir
RESTORE_DIR --confirm TOKEN_FROM_PREVIEW`. Require a `restored` result and
start the candidate with `--data-dir RESTORE_DIR`. Compare the restored fixture
through Mentat, then stop it with `--data-dir RESTORE_DIR`.

Next, prove uninstall/reinstall preservation with the upgraded
`UPGRADE_DIR`: stop the candidate, uninstall only the application, confirm the
fixture files still exist in `UPGRADE_DIR`, reinstall the exact candidate,
start with `--data-dir UPGRADE_DIR`, compare the same fixture data, and stop.

Finally, prove rollback: stop Mentat, remove only the application, install the
recorded previous package, and restore the pre-upgrade backup into another
clean test data directory. On macOS, move `Mentat.app` from Applications to
Trash. On Windows, use **Installed apps → Mentat → Uninstall**. For pipx, use
`pipx uninstall mentat-local`. Never remove the Mentat data folder during an
application-only uninstall.

Record the result and tester for every row:

| Check | Intel Mac | Apple Silicon + Rosetta | Windows | pipx |
| --- | --- | --- | --- | --- |
| Clean install and first start |  |  |  |  |
| Backup before upgrade |  |  |  |  |
| Upgrade from the recorded previous release |  |  |  |  |
| Restore that backup into a clean install |  |  |  |  |
| Uninstall, reinstall, and find the same operator data |  |  |  |  |
| Roll back to the previous release |  |  |  |  |

Compare tasks, projects, settings, Context Packs, and retained Console history
after restore.

This guide is the artifact-install authority. [README.md](README.md) covers the
source-development setup. Native installers are the supported macOS and
Windows paths. `pipx` is supported on Python 3.11–3.13; Linux remains
preview-only.

## 3. Accept or replace it

Accept the candidate only when another person installed the exact files using
public docs, every row above passes, and no P0 or P1 issue remains.

If the candidate is bad, mark its GitHub prerelease title and notes
**Withdrawn**. Keep its tag and files visible, explain why it was withdrawn,
fix the issue, and publish the next number (for example, `rc.2`). Never delete
or move a release tag to hide history.

If publishing fails after the tag is pushed, use only the
`mentat-release-recovery-bundle` artifact from that same protected workflow
run. Confirm its manifest names the tag and exact tag commit, recheck
`SHA256SUMS`, and use GitHub's release page to finish missing notes/assets for
that tag. Never rebuild or replace an asset. If an existing asset conflicts,
mark the partial release withdrawn and issue a new version; do not move the tag.
