# Final current fixture integration

Base: 101c6d3. This fixture-only branch restores the exact approved fa9fda3 versions of `tests/test_hermes_webhook_routes.py` and `tests/test_mentat_db_current.py`.

The webhook seed again uses canonical `todo` with explicit nullable task metadata. The main-database mutation test again checks the current typed error, exactly three captures and two existing pauses, and no temporary snapshot materialization. Production code, deadlines, skips, and all other fixture assertions are unchanged.

The original 101 full run remains preserved and unmodified. Its separate permission-fixture failures arise from the caller inheriting umask 077; the reviewed caller correction sets only the test child to umask 022. That correction does not resolve the two restored fixture omissions by itself.

This source checkpoint has not run tests or publication checks. The earlier fa9 passing results do not qualify this new branch. Final checks require the reviewed complete fixture cohort and separately authorized execution; package, actual local journey, and native helper-origin verification remain separate evidence.
