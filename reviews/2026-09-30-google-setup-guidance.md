# Google setup failure guidance

Scope: guided CLI onboarding under the [Google owner activation issue](https://github.com/hazeion/agent-os/issues/241).
The existing terminal ceremony reports one generic message for failures in
host verification, ceremony preparation, gateway startup, browser proof,
listener teardown and owner confirmation.

Add fixed, stage-specific terminal guidance. Stage labels and suggested checks
come only from an internal allowlist; never interpolate exception text,
provider responses, credentials or supplied paths. Keep the foreground-terminal
gate, exact owner confirmation, validated backup and existing cleanup ordering.
This changes no authentication, provider call, configuration or remote authority.
After confirmation returns successfully, an output failure must explain that
the owner was already confirmed, rather than imply that the prior owner remains.

Verification strategy: inject private-canary exceptions at each stage; require
the correct bounded guidance without canary disclosure, unchanged confirmation
count and listener-before-ceremony cleanup. Retain successful enrollment/recovery
and foreground-terminal tests, then run the real Node/Python synthetic-provider
setup flow on Linux. Obtain two independent reviews before publishing a full PR.

Local verification: all four portable CLI methods pass, including eight
failure/interrupt subcases and the unverified-shutdown fence. All 17 selected
Linux CLI/ceremony/reservation/guardian/real-Node flow methods pass without skips;
the Node flow uses a synthetic Google provider and real disposable backups.
Compilation, wheel/sdist inventory and exact packaged CLI bytes pass.

Status: both independent reviews clear. The second reviewer also independently
reran all four portable CLI methods. Real Google, operator TLS, human security
and physical-device acceptance remain separate gates.
