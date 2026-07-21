# Security

Thanks for helping keep Mentat users safe.

## Supported versions

During beta, security fixes target the newest published `0.1.x` beta only. Old
source snapshots and unreleased branches are not supported release channels.

## Report a vulnerability privately

Please use [GitHub's private security advisory form](https://github.com/hazeion/agent-os/security/advisories/new).
Do not open a public issue for a possible vulnerability.

Include the affected Mentat version, a short impact description, safe steps to
reproduce it, and a redacted diagnostics bundle if useful. Never include API
keys, credentials, private conversations, note contents, or other personal
data.

This is a single-developer beta. I will make a best-effort acknowledgement and
prioritize confirmed data-loss, secret-exposure, unsafe-mutation, and app-wide
availability issues, but there is no guaranteed response-time SLA.

## Security boundaries

- Mentat accepts dashboard traffic on loopback only and is designed for one
  local operator. It is not a remotely hosted multi-user service.
- Mentat reads Hermes state through supported interfaces and mutates Hermes
  only through fixed, validated, capability-gated operations. It does not
  directly edit Hermes core files.
- A configured remote Hermes endpoint is a separate trust boundary. Mentat
  makes server-to-server HTTPS requests to the operator-supplied endpoint. The
  operator is responsible for trusting and securing that runtime.
- Hermes owns provider credentials and authentication. Mentat does not expose
  credential values to the browser.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete capability and mutation
contract.
