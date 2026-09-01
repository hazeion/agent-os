# Cascade-delete Project work as one confirmed operation

Status: accepted

Deleting a Project or Task removes its transitive dependent Tasks across
Projects and each associated Conversation, Run, event, artifact, and local
planning record. Mentat must first stop every affected active local or external
operation and verify the stop; otherwise deletion aborts without erasing
anything. Hermes-owned terminal history remains under Hermes authority, and
Mentat retains only a content-free deletion receipt to reject stale events and
repeated requests.
