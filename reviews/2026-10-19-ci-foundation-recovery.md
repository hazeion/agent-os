# CI foundation recovery

Status: final verification in progress before publication.

The owner requested finishing the open work, starting with a current checkout
and repair of CI failures. This branch starts at PR #243 head `1bdb4a4` and
preserves that PR's original scope and all existing gates. No PR merge or
production activation is included.

## Changes and checks

The recorded quality failure is the braces dependency audit. Fresh inspection
also finds newer advisories in Next, sharp and source-map-js. Pin Next and
eslint-config-next to patched 16.3.8 and refresh compatible transitive locks.
Braces has no published fixed version. Replace the Next lint plugin's sole
fast-glob call with a local directory-only adapter using tinyglobby 0.2.17.
The adapter disables recursive directory expansion, preserves literal roots
and absolute/relative results, and rejects unsupported call shapes.

Regression tests cover default, explicit, wildcard, brace, array, absent and
filesystem-root paths, nested-directory exclusion, and the actual Next
no-html-link-for-pages rule. A nested unrelated fixture page must not become
an application route. Fresh npm ci resolves the adapter through a
repository-relative link and reports zero vulnerabilities. No detector,
audit threshold, lint rule, CI timeout or existing test is disabled.

The Windows request failure at the stack tip traces to file-backed expected
Agent-schema creation. Build this synthetic DDL in a closed in-memory
database, preserving the exact complete migration/signature comparison.
This common repair applies equally to the foundation's earlier schema.
Its 32 Agent registry and Node contract tests pass locally on Python 3.13.14.
The tip's separate regression run passed 38 related tests and the previously
timed-out cold bridge request plus nine gate tests.

Two independent read-only reviews inspected the Python, dependency and
adapter changes. They caught the initial direct alias's recursive-root
behavior and Windows path normalization in a new assertion; both were
corrected and covered. No credentials or owner services are used.

Full web checks, production build, and final review readback are in progress.
Hosted multi-platform checks and propagation through the existing PR stack
remain required. Integrated owner/provider/host/garage acceptance remains
separate and incomplete.
