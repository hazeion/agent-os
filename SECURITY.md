# Security

Thanks for helping keep Mentat users safe.

## Supported versions

Once public beta releases begin, security fixes will target the newest `0.1.x`
beta. Until then, `main` is a development build rather than a supported release
channel.

## Report a vulnerability privately

Please use [GitHub's private security advisory form](https://github.com/hazeion/agent-os/security/advisories/new).
Do not open a public issue for a possible vulnerability.

Include the Mentat version or commit, a short impact description, safe steps to
reproduce it, and a redacted diagnostics bundle if useful. Never include API
keys, credentials, private conversations, note contents, or other personal
data.

This is a single-developer beta. I will make a best-effort acknowledgement and
prioritize confirmed data-loss, secret-exposure, unsafe-mutation, and app-wide
availability issues, but there is no guaranteed response-time SLA.

## Security boundaries

- Mentat accepts dashboard traffic on loopback only and is designed for one
  local operator. It is not a remotely hosted multi-user service.
- In the Next.js preview, the browser connects only to the local Node gateway.
  Node reaches Python through fixed private bridge capabilities and a temporary
  process token. The bridge is not a generic proxy.
- Mentat reads Hermes state through supported interfaces and mutates Hermes
  only through fixed, validated, capability-gated operations. It does not
  directly edit Hermes core files.
- A configured remote Hermes endpoint is a separate trust boundary. Mentat
  makes server-to-server HTTPS requests to the operator-supplied endpoint. The
  operator is responsible for trusting and securing that runtime.
- Remote Hermes API keys are loaded only from a selected environment variable
  or owner-only env file. They are not accepted as CLI values or browser
  requests and are excluded from normal backups and diagnostics.
- Hermes owns provider credentials and authentication. Mentat does not expose
  credential values to the browser.
- Codex execution uses one fixed local App Server stdio process and the CLI's
  existing sign-in. Mentat does not collect Codex credentials or expose Codex
  configuration, account details, thread IDs, or turn IDs to the browser.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete capability and mutation
contract.
