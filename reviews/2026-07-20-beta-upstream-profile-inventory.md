# Milestone 2 upstream blocker — authenticated profile inventory

Status: implemented and published upstream as a draft; Mentat integration remains blocked pending upstream merge and release

## Goal

Add the smallest supported Hermes HTTP contract that lets an authenticated
control plane discover every canonical profile ID without reading remote files,
using a dashboard session token, or exposing private profile configuration.

Mentat will remain fail closed until the capability is merged, released,
advertised, and independently verified against an installed Hermes version.

## Standing approval and review timing

The maintainer approved every remaining Road to Beta slice without another
scope, test, commit, push, or publication pause. The two independent
adversarial reviews remain deferred until every Milestone 2 slice is complete.

## Upstream baseline

- `GET /v1/models` identifies the profile/model serving one route, but it is
  not a complete profile roster.
- Multiplex routing can serve known profiles under `/p/<profile>/...`, but
  external clients cannot safely discover the complete set.
- Hermes' richer local `ProfileInfo` includes paths, provider/model metadata,
  aliases, distributions, environment presence, skill counts, and user-authored
  descriptions. Those fields are not required for remote discovery.
- Kanban dashboard profile routes use a separate browser/session boundary and
  are not the stable API-server bearer contract approved for Mentat.

## Scope

### Included

- Bearer-authenticated `GET /v1/profiles` on the API server.
- A versioned, complete, bounded roster of canonical profile IDs.
- Exact default, current-route active, and current-gateway served flags.
- Single-profile and multiplex behavior.
- Capability and endpoint advertisement plus operator/developer docs.
- All-or-nothing validation for duplicates, unsafe IDs, oversized inventories,
  missing active-profile reconciliation, and enumeration failures.

### Excluded

- Profile creation, deletion, rename, cloning, import/export, or activation.
- Profile identity or `SOUL.md` reads/writes.
- Descriptions, paths, aliases, distributions, provider/model settings,
  environment state, skill inventories/counts, credentials, or config files.
- A claim that every discovered profile is served by the current gateway.
- Mentat UI/adapter enablement before upstream availability.
- README changes; first-run installation guidance is unchanged by this
  upstream contract slice.

## Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Capabilities advertise a distinct versioned, complete profile-inventory feature and fixed endpoint only when API-key authentication is configured. | Capability tests | Complete |
| AC-2 | The endpoint requires the configured bearer key before enumeration and rejects missing/invalid authentication. | Auth-order tests | Complete |
| AC-3 | The response contains every canonical profile ID with only object, default, active, and served fields. | Schema and single/multiplex tests | Complete |
| AC-4 | Paths, descriptions, providers/models, aliases, distributions, environment state, skills, credentials, and raw errors are absent. | Allowlist/privacy tests | Complete |
| AC-5 | Duplicate, unsafe, oversized, incomplete, or unreconciled inventories fail closed rather than returning partial data. | Negative tests | Complete |
| AC-6 | Existing models, profile routing, API endpoints, and local profile behavior remain unchanged. | Regression tests | Complete |
| AC-7 | Focused and expanded tests, lint/compile/docs checks, branch publication, and a draft upstream PR complete. | Verification record | Complete |

## Proposed wire contract

```text
GET /v1/profiles
Authorization: Bearer <API_SERVER_KEY>
```

```json
{
  "object": "list",
  "version": 1,
  "complete": true,
  "active_profile": "default",
  "data": [
    {
      "id": "default",
      "object": "hermes.profile",
      "is_default": true,
      "is_active": true,
      "served": true
    }
  ]
}
```

`served` means the current gateway can serve that profile. A single-profile
gateway serves only its active profile; a multiplex gateway serves the complete
roster. The response contains no paths or free-form metadata.

## Test strategy

| Area | Planned evidence |
| --- | --- |
| Contract | Version, completeness, capability flags, exact endpoint |
| Authentication | No configured key, missing bearer, wrong bearer, valid bearer |
| Inventory | Default and named IDs, single-profile served state, multiplex served state, prefixed active route |
| Fail closed | Duplicate/unsafe IDs, missing active ID, oversized roster, helper failure |
| Privacy | Exact response allowlist and forbidden-field/path assertions |
| Regression | Full API-server surface, profile core, multiplex routing, compile/lint/docs |

## Implementation record

- Added bearer-authenticated `GET /v1/profiles` to the Hermes API server and
  its multiplex route mirrors.
- Required a configured API key before enumeration and advertised the feature
  as unavailable when the server has no key.
- Built the response from Hermes' lightweight canonical profile roster rather
  than the richer local `ProfileInfo` objects.
- Returned only canonical IDs and default, current-route active, and
  current-gateway served state.
- Derived served flags from the same complete roster snapshot, avoiding a
  second directory scan that could race a concurrent profile change.
- Rejected inventories above 1,000 entries, unsafe/noncanonical IDs,
  duplicates, a missing default, or a missing active profile.
- Added user/developer API documentation without changing local profile CRUD or
  Mentat's README.

## Verification record

- Focused endpoint/capability contract: **14 passed**.
- Complete main API-server module plus multiplex routing: **224 passed**.
- Complete API-server surface: **405 passed**.
- Hermes profile-core module: **155 passed**.
- Post-rebase gate on current upstream `main`: **14 focused passed** plus
  **161 profile/multiplex passed**.
- Python compilation, Ruff, and `git diff --check`: passed.
- Docs diagram lint: **365 files checked, 0 errors**.
- Docusaurus production build: passed for English and zh-Hans. It emitted
  existing unrelated link warnings and used supported fallback indexes because
  the local system Python lacked PyYAML and the sandbox could not fetch the live
  skills index.
- The post-rebase verification ran against upstream `main` commit
  `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`.

## Publication packet

- Fork: `hazeion/hermes-agent`
- Branch: `feat/http-profile-inventory`
- Commit: `d219a3415ae2d455c6e5056884ac09a6911d7197`
- Upstream draft PR:
  [NousResearch/hermes-agent#68190](https://github.com/NousResearch/hermes-agent/pull/68190)
- Mentat must not advertise or enable this integration until the upstream
  capability is merged, released, and independently verified against the
  installed Hermes runtime.
