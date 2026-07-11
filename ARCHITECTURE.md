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

Deferred until separately approved:

- direct `SOUL.md` editing;
- clone-all;
- profile rename or deletion;
- skill content editing, hub installation, or arbitrary MCP configuration;
- provider switching;
- non-loopback access.

Mentat retains one active dashboard run globally for the first version. This
can be revisited after profile-scoped execution and cancellation are proven.
