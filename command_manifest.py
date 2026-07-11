"""Versioned allowlist of slash commands implemented by Mentat.

This manifest describes dashboard handlers, not Hermes CLI commands. Keeping it
project-owned and static prevents browser input or unstable CLI output from
expanding the command surface.
"""

from __future__ import annotations

from copy import deepcopy


COMMAND_MANIFEST_SCHEMA_VERSION = 1

_COMMAND_MANIFEST = {
    "schema_version": COMMAND_MANIFEST_SCHEMA_VERSION,
    "source": "mentat",
    "capabilities": {
        "commands.manifest.read": True,
        "commands.external_source": False,
        "commands.hermes_cli_passthrough": False,
    },
    "commands": [
        {
            "command": "/model",
            "handler": "agent_console.refresh_models",
            "arguments": [{
                "name": "model",
                "required": False,
                "description": "Optional active-provider model to select for review.",
            }],
            "description": "Refresh current provider models",
            "safety": "read_only",
        },
        {
            "command": "/new",
            "handler": "agent_console.new_session",
            "arguments": [],
            "description": "Start a new Hermes session",
            "safety": "local_state",
        },
        {
            "command": "/help",
            "handler": "agent_console.show_help",
            "arguments": [],
            "description": "Show dashboard commands",
            "safety": "read_only",
        },
    ],
}


def command_manifest_payload() -> dict:
    """Return an isolated copy so request handlers cannot mutate the allowlist."""

    return deepcopy(_COMMAND_MANIFEST)
