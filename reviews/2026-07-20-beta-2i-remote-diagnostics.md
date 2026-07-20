# Milestone 2I — Remote Hermes diagnostics

Status: implementation complete and locally verified; milestone-level adversarial review deferred until all Milestone 2 blockers are resolved

## Scope

- Keep existing local Hermes diagnostics unchanged.
- In remote mode, use only the selected connection's authenticated, validated readiness and capability discovery.
- Show fixed healthy, degraded, unreachable, unauthenticated, or unsupported states.
- Suppress the endpoint, API key, binding ID, raw upstream details, and irrelevant local Hermes paths.
- Keep the Settings config summary lightweight and connection-aware.

## Compatibility audit

- Installed Hermes: `0.18.2` at local commit `4281151ae859241351ba14d8c7682dc67ff4c126`.
- Current upstream inspected: `31c08a9aad6e83ded5d0e55dc7d41b94a99f08a1`.
- Both advertise authenticated `/health/detailed` and `/v1/capabilities` with the bounded data Mentat needs for diagnostics.
- Current upstream still lacks exact request-bound approval responses, typed HTTP clarification handling, a stoppable continuation contract, complete API-key-authenticated profile inventory, and revision-aware API-key-authenticated Kanban.
- Runs still documents simple text input; inline image support remains on chat/responses rather than the status/stop Runs lifecycle.

## Verification

- `python3 -m py_compile health_checks.py remote_hermes.py server.py`
- `node --check public/app.js`
- `python3 -m unittest tests.test_remote_hermes tests.test_health_signal_upgrade tests.test_config_summary_security tests.test_remote_capability_inventory tests.test_hermes_transport -v`
  - 66 passed.
- `python3 -m unittest discover -s tests -v`
  - 693 passed; 4 expected platform skips.

## Review policy

Per maintainer direction, the two independent adversarial reviews run once the whole Milestone 2 implementation is complete, not after this slice alone.
