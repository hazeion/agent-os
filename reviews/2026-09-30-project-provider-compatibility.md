# Project provider compatibility audit

Status: source/contract evidence; no credential resolution, model submission,
provider choice, new auth registration or execution approval. The inspected
official Hermes release remains unchanged 0.21.5 at
`f97608f178d1ffeca59860195ab7da295f7c8e5f`. Machine-local metadata stays in
ignored operator artifacts. Mentat did not directly read an owner auth/token
store, call an auth resolver, inspect credential values or return credentials.

## Current boundary

The schema-43 journal policy and synthetic broker require one irrevocable
inference reservation and construct a request with an explicit output-token
limit. The 127-test Linux qualification proves selected input containment,
public artifact origin, stock transport to the fake broker and durable local
accounting. It does not prove that every provider reachable by an ordinary
Hermes profile enforces that policy. A configured provider or working Console
is not a Project runtime qualification.

## Supported credential resolution is not a pure lookup

The stock [runtime resolver](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/hermes_cli/runtime_provider.py#L975)
returns a private credential/runtime dictionary. Only a trusted host-side
Hermes helper may invoke it; that dictionary must never cross worker, Node or
browser boundaries. Its [resolution ladder](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/hermes_cli/runtime_provider.py#L1037)
can select pools, refresh OAuth, choose custom/external providers or fall back
from `auto`. Matching a provider name after resolution cannot undo those
side effects. [Provider discovery](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/providers/__init__.py)
may import installed and owner-home code before a result is returned.

The supported [plugin LLM surface](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/website/docs/developer-guide/plugin-llm-access.md)
deliberately supports provider fallback and retries. It cannot substitute for
one fixed physical submission owned by Mentat's committed call journal.
Qualification must establish exact profile/source identity, supported API,
fixed endpoint and request semantics, credential custody, no unexpected plugin
initialization, no fallback and no second physical send after an unknown result.
Neither a generic resolver name nor SDK `max_retries=0` proves those facts.

## Stock Codex OAuth does not satisfy the existing token-limit policy

The [Codex transport](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/agent/transports/codex.py#L773)
omits `max_output_tokens` for the Codex backend. The
[auxiliary shim](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/agent/auxiliary_client.py#L1499)
records rejection of that parameter by the endpoint. Its
[streaming runtime](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/agent/codex_runtime.py#L1009)
also has an outer transport retry. A newly qualified host transport could
remove duplicate physical sends, but local byte truncation or worker death
does not impose a provider-side token/cost ceiling. Do not silently drop the
stored policy field, relabel an unknown request or advertise this route as
qualified for the existing Project policy. Ordinary Console support is separate.

The [read-only OAuth resolver](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/hermes_cli/auth_codex.py#L550)
avoids normal CLI adoption, refresh, quota probing and auth-lock creation.
However, its [auth-store reader](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/hermes_cli/auth.py#L661)
may attempt a corrupt-file backup, and its
[pool fallback](https://github.com/NousResearch/hermes-agent/blob/f97608f178d1ffeca59860195ab7da295f7c8e5f/hermes_cli/auth.py#L870)
may read a global root rather than the selected profile. Therefore `read_only`
does not by itself prove no writes or exact credential-scope ownership.
Endpoint overrides must likewise be excluded or verified before any submission.
No such resolver was invoked in this audit.

## Documented alternatives still need a choice and qualification

Official [Sign in with ChatGPT guidance](https://developers.openai.com/siwc/quickstart)
describes separately authorized OAuth access to eligible Responses requests
for open-source apps without an API key. Its
[inference contract](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
uses the public Responses endpoint, `store=false`, streamed terminal evidence
and account-specific model selection. This is a distinct registration/consent
flow, not permission to reuse an existing Hermes Codex token at a different
endpoint. The docs do not establish this account's eligibility or prove the
exact requested token/vision limits; those remain explicit qualification gates.
It is a candidate credential route, not a selected implementation or a claim
of readiness. The [self-hosted VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
requires local authorization for the same user/workspace, a stable VM host ID,
protected selected-session transfer and VM-owned refresh. It explicitly lacks
host-specific attribution/revocation for transferred sessions; Mentat's own
local fences cannot be described as provider-side per-host revocation.
The [overview](https://developers.openai.com/siwc/token-sharing-open-source)
separately addresses paid/remotely hosted services. Do not infer that a
personal self-hosted VM establishes eligibility for a different deployment.

Alternatively, the operator can select a dedicated supported API-key provider
through Hermes. It still requires exact profile/credential-source isolation,
fixed host/model and one-submission/token/image/unknown-outcome qualification.
No API key was inspected, created or requested in this audit, and no billed
provider route was selected automatically.

The owner has been asked which credential route to evaluate. Google OIDC
dashboard access remains a separate existing workstream. No auth migration,
policy weakening, provider fallback, Run source or Agent capability follows
from these findings. Keep Project production dispatch unavailable. Exact owner
plan approval and checkpoint admission must ultimately bind a qualified runtime
and current immutable Task inputs; they cannot pretend to approve execution
against an unavailable or changed qualification.

## Verification and review

Source reads plus a supported metadata-only config inspection established the
provider category without credential resolution or model work. All source
references target the pinned official release; OpenAI documentation was fetched
on September 30, 2026. This record makes no live-provider acceptance claim.
Both independent final read-only contract reviews are clear. Review corrected
the precise resolver source anchor and remote-host eligibility/revocation
wording. Diff checks pass; executable/runtime code is unchanged.
