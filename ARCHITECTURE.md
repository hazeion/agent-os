# Mentat Architecture and Capability Contract

## Product role

Mentat is a local-first, capability-scoped Hermes control plane. It is not only
a read-only viewer, and it is not a general-purpose editor for Hermes files.
Mentat may observe Hermes state broadly, but it may mutate Hermes only through
explicit, supported capabilities implemented by the Hermes adapter.

## Identity model

- A Hermes **profile** is the canonical executable agent identity.
- A Mentat **heartbeat agent** is an observation about a running or recently
  completed process. Records in `data/agents.json` are not profile definitions.
- A Hermes **session** is conversation history owned by a specific profile.
- Mentat must not create a second agent registry that competes with Hermes.

## Write boundaries

| Surface | Policy |
| --- | --- |
| Hermes sessions and `state.db` | Read-only |
| Credentials and authentication files | Never read or write directly |
| Hermes profiles | Mutate only through approved, fixed Hermes CLI/API operations |
| Model/provider configuration | Mutate only through validated Hermes operations |
| Skills and `SOUL.md` | Read-only until a separate capability is approved |
| Mentat runtime history | Writable, private, and gitignored |
| Mentat project/task data | Writable through allowlisted project-owned storage |
| Arbitrary Hermes files | Never write directly |

## Mutation contract

Every write-capable Hermes operation must declare:

1. a typed intent and fixed handler; browser input never becomes a command;
2. capability and Hermes-version requirements;
3. input validation and affected profile scope;
4. preview and human-confirmation requirements;
5. concurrency and locking rules;
6. verification, partial-failure, and rollback behavior;
7. privacy-aware local audit data that excludes secrets.

Unsupported capabilities and unknown Hermes versions fail closed. Mentat never
constructs a shell command from browser text and never collects Hermes secrets.

Agent Console execution is globally single-run in v1. Every run records its
Hermes profile id, launches with a fixed `-p <profile>` selector, and may resume
only a session already associated with that same profile.

## Provider switching boundary

Provider discovery and selection are scoped to the selected Hermes profile.
Mentat obtains picker context from Hermes through `load_picker_context()` and
builds the selectable inventory with
`build_models_payload(..., explicit_only=True, picker_hints=True)`. The browser
may therefore see only providers Hermes reports as explicitly configured and
authenticated for that profile, plus whether each provider is current. It must
not receive credential values, credential paths, environment-variable names,
tokens, or an unfiltered catalog of every provider Hermes supports.

Hermes remains the sole owner of provider credentials and authentication.
Mentat does not add, edit, validate, migrate, or delete credentials. Provider
switching is an approved, fixed Hermes adapter capability with these rules:

- the requested provider must be present in the profile-scoped authenticated
  inventory returned by Hermes;
- the current provider is reported separately from the authenticated set;
- Mentat previews the affected profile, current provider, requested provider,
  and model implications before requiring profile-bound confirmation;
- switching is blocked while an Agent Console run is active;
- Mentat refreshes Hermes picker context after the operation to verify the
  selected provider and models;
- a failed verification triggers rollback to the previous provider when Hermes
  supports it, otherwise Mentat reports the partial failure and fails closed.

This boundary covers selection among already authenticated providers only.
Credential setup and reauthentication continue to happen through Hermes.

Agent Console progress is exposed as versioned, structured Mentat events. Event
sequence numbers are monotonic within a run and double as polling cursors. The
browser requests only events newer than its cursor and merges them into its local
run view; the full-run response remains available for compatibility and recovery.
Events describe Mentat-owned lifecycle transitions only. Mentat does not parse
unstable native Hermes output into synthetic tool-call events, and it does not
require a streaming transport for this local-first contract.

Agent Console slash commands come from Mentat's versioned, project-owned safe
command manifest. Each entry declares its dashboard handler, arguments,
description, and safety classification. The frontend accepts only the current
schema and a fixed handler registry. The initial allowlist is `/model`, `/new`,
and `/help`; this is intentionally distinct from the full Hermes CLI.

Future command sources must be introduced as an explicit capability and emit
the stable Mentat schema. Mentat does not parse CLI help/output to discover
commands, and it never provides arbitrary Hermes CLI passthrough.

## Initial agent-creator scope

The first version may create a fresh profile or clone approved configuration
through supported Hermes operations. It may collect a profile name,
description, creation mode/source, and skill-seeding choice.

Approved for the initial creator:

- default Hermes bundled skills;
- no bundled skills for a fresh profile;
- an explicit enabled subset selected from Hermes' built-in skill catalog.

Skill selection uses a capability-gated Hermes runtime operation. Mentat stores
skill identifiers only; it does not edit skill contents or copy skill files.

Approved for Managed Agents:

- deletion of a non-default, non-active Hermes profile when Hermes advertises
  `profiles.delete`;
- an exact preview and profile-bound confirmation token before deletion;
- blocking deletion while any Mentat Agent Console run is active;
- post-operation profile discovery to verify the profile was removed.
- profile-scoped provider/model configuration using the same authenticated-only
  inventory, preview, confirmation, active-run lock, verification, and rollback
  contract as the Agent Console. This is the configuration path for a fresh
  profile that does not yet have a provider assigned.

Deletion is performed only through Hermes' supported profile API in its own
runtime. Mentat never deletes profile directories or their contents directly.

Deferred until separately approved:

- direct `SOUL.md` editing;
- clone-all;
- profile rename;
- skill content editing, hub installation, or arbitrary MCP configuration;
- non-loopback access.

Mentat retains one active dashboard run globally for the first version. This
can be revisited after profile-scoped execution and cancellation are proven.
