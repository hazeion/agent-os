"""Canonical inventory for auditing Mentat's Hermes integration contracts."""

from __future__ import annotations


# Every boolean capability accepted by remote_hermes.py belongs to exactly one
# independently reviewable contract. Tuples let tests detect duplicate mapping.
REMOTE_FEATURE_CONTRACTS = {
    "remote_openai_api": (
        "chat_completions", "chat_completions_streaming",
        "responses_api", "responses_streaming",
    ),
    "remote_runs_core": (
        "run_submission", "run_status", "run_events_sse", "run_stop",
        "run_steer", "tool_progress_events",
    ),
    "remote_run_recovery": (
        "run_event_replay", "run_pending_action_status", "run_runtime_identity",
    ),
    "remote_approval_and_clarification": (
        "run_approval_response", "run_approval_request_binding",
        "run_approval_structured_preview", "approval_events",
        "run_clarification_response", "run_clarification_request_binding",
        "clarification_events",
    ),
    "remote_session_resources": (
        "session_resources", "session_chat", "session_chat_streaming", "session_fork",
    ),
    "remote_session_continuation": (
        "run_session_continuation", "run_session_continuation_exact_revision",
        "run_session_continuation_stoppable",
    ),
    "remote_inline_images": ("run_inline_images",),
    "remote_profile_inventory": (
        "profile_inventory", "profile_inventory_complete",
        "profile_inventory_requires_api_key",
    ),
    "remote_profile_runtime": (
        "profile_runtime_inventory", "profile_runtime_inventory_complete",
        "profile_runtime_inventory_requires_api_key", "profile_runtime_switch",
        "profile_runtime_switch_revision_bound", "profile_runtime_switch_idempotency",
        "profile_runtime_switch_active_run_lock",
    ),
    "remote_skill_toolset_inventory": ("skills_api",),
    "remote_kanban_mutation": (
        "kanban_api", "kanban_api_revisioned", "kanban_api_idempotency",
        "kanban_api_requires_api_key",
    ),
    "remote_artifact_download": (
        "kanban_artifacts", "kanban_artifacts_requires_api_key",
        "kanban_artifacts_digests",
    ),
    "remote_cron_inventory": ("jobs_inventory",),
    "remote_prohibited_admin": ("admin_config_rw", "jobs_admin"),
}

LOCAL_CONTRACTS = (
    "native_observer_hooks", "browser_projection_stream",
    "browser_periodic_refresh", "server_periodic_reconciliation",
    "local_console_live_progress", "local_console_final_usage",
)

ALL_CONTRACT_IDS = frozenset((*LOCAL_CONTRACTS, *REMOTE_FEATURE_CONTRACTS))

# These values are mirrored exactly in the audit table. The disposition token
# appears in each decision cell so tests cover every classification and outcome.
CONTRACT_CLASS_AND_DISPOSITION = {
    "native_observer_hooks": ("Stock equivalent", "Migrated"),
    "browser_projection_stream": ("Mentat-local", "Retain"),
    "browser_periodic_refresh": ("Supported fallback", "Retain"),
    "server_periodic_reconciliation": ("Supported fallback", "Retain"),
    "local_console_live_progress": ("Custom enhancement", "Retain"),
    "local_console_final_usage": ("Stock partial", "Migration candidate"),
    "remote_openai_api": ("Stock equivalent", "Prefer stock"),
    "remote_runs_core": ("Stock equivalent", "Prefer stock"),
    "remote_run_recovery": ("Custom required", "Retain"),
    "remote_approval_and_clarification": ("Custom required", "Retain"),
    "remote_session_resources": ("Stock equivalent", "Prefer stock"),
    "remote_session_continuation": ("Custom required", "Retain"),
    "remote_inline_images": ("Custom required", "Retain"),
    "remote_profile_inventory": ("Custom required", "Retain"),
    "remote_profile_runtime": ("Stock partial", "Migration candidate"),
    "remote_skill_toolset_inventory": ("Stock equivalent", "Prefer stock"),
    "remote_kanban_mutation": ("Custom required", "Retain"),
    "remote_artifact_download": ("Custom required", "Retain"),
    "remote_cron_inventory": ("Custom required", "Retain"),
    "remote_prohibited_admin": ("Explicitly prohibited", "Prohibit"),
}
