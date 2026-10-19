# Support only fresh and current storage

Status: accepted, October 19, 2026

The owner chose fresh/current storage instead of maintaining unused upgrade and
old-backup conversion paths while the integrated product is still being
qualified. Mentat supports current SQLite schema 46, backup format 5 and restore
protocol 4; older, future, malformed and unsafe storage is refused without
conversion, deletion or overwriting operator data. Current row integrity,
authority receipts, unknown outcomes, capacity, privacy and validated recovery
remain required.

Existing older data must be kept separately with an appropriate older build or
a fresh directory selected for this build. Current backup/restore and offline
SQLite-to-JSON `task-export` remain available; migration commands, old archive
restores, standalone Agent-registry convergence and schema5 sibling export are
retired. This supersedes the storage-upgrade and older-backup provisions in
[ADR0001](0001-conversation-owned-agent-console.md), not its Conversation, Turn
and Run ownership decision.
