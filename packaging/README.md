# Native packaging

Mentat uses one folder bundle on both tier-one platforms:

- macOS: a `Mentat.app` bundle inside a signed and notarized `.pkg` installer.
- Windows: a `Mentat` folder bundle inside a signed Inno Setup `.exe` installer.

PyInstaller bundles the matching platform's Python runtime, so operators do not
need to install Python. It is not a cross-compiler: build macOS artifacts on
macOS and Windows artifacts on Windows.

## Local test bundle

Install the pinned tools, then build from the repository root:

```bash
python -m pip install --require-hashes -r requirements-native.lock
python scripts/build_native.py
```

The bundle contains only the app, static UI, and public seed data. Operator
data remains in Mentat's platform data directory and survives app removal.

Unsigned bundles are test artifacts only. Release signing and macOS
notarization must run in a protected trusted release environment. Signing
credentials must never enter source, pull-request jobs, ordinary artifacts,
logs, diagnostics, or browser-visible state.

The native lock is generated from `requirements-native.in` with pip-tools
7.6.0. It includes the pure-Python helpers for both native platforms so the
same hash-checked dependency set is used on macOS and Windows.

## Release candidates

The protected **Signed beta artifacts** workflow builds the signed native
installers and verified Python package from one exact `main` commit. It then
creates checksums, a manifest, short release notes, and a numbered prerelease.

Before sharing one, complete [the release rehearsal](../RELEASE_REHEARSAL.md).
Keep a bad candidate visible as withdrawn and replace it with the next RC
number; never move or delete its tag.
