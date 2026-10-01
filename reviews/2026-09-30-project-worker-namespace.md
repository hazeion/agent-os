# Fixed stock-Hermes proposal worker namespace

Implement the approved Mentat controller's Linux namespace handoff and
credential-free completion frontend. This is a private runtime component,
not a browser route or Run admission. Project dispatch guards remain intact.

The existing scope factory starts an inert bootstrap, pins the kernel process,
invocation and cgroup generation, verifies effective limits and starts an
independent watchdog before one irreversible descriptor handoff. A lost or
failed handoff cannot launch another worker. EOF/failure/Stop terminates the
owned namespace; local emptiness is verified before ownership handles close.
Effective memory/process/CPU limits are re-read immediately before transfer.
Readiness, terminal readback, bootstrap exit and verified cleanup must remain
inside the absolute wall even if a queued packet beats the watchdog callback.
Removed held cgroup control files may report ENODEV; success still requires
the held cgroup2 inode and inactive exact original invocation readback.

Runtime root descriptors pin only their inodes. A complete immutable official
release/dependency qualification remains a separate required admission gate;
sentinels and a private caller-supplied path are not that attestation. Query,
image, frontend code and config bytes use kernel-sealed snapshots. The fixed
Bubblewrap command requires user/PID/network/IPC/UTS/cgroup namespaces,
disabled nested user namespaces, no capabilities, a read-only root, individual
read-only inputs/runtime roots, and bounded tmpfs HOME (16 MiB), /tmp (8 MiB)
and exports (32 MiB). No owner home, Windows mount, host bus or cgroup filesystem
is mounted. The frontend closes all inherited mount-source descriptors before
starting Hermes, preventing outside-directory-FD traversal. Only its broker
and lifecycle sockets remain; neither is inherited by Hermes children.

The stock CLI runs against a synthetic home with supported fixed config
set/get readback: native image input, exact declared vision state, title
generation disabled, one API attempt and no recovery cycles. HERMES_SAFE_MODE=1,
ignore-rules, the qualified empty bot_room toolset and fixed custom local
endpoint prevent loading owner configuration or tools. CLI --safe-mode and
--ignore-user-config are omitted because they discard this required synthetic
config and can silently caption images. An actual model's vision capability
must be qualified before a host supplies that state; it is not inferred here.

The namespace-local HTTP listener accepts only bounded streamed completions
for the frozen model with no declared tools. It denies metadata and alternate
paths, transfer encoding and duplicate Content-Length.
Native image blocks must decode to the exact prepared image digest; missing,
substituted, duplicate, externally linked or unprepared images fail before
the broker. This also rejects silent text/caption fallback at the wire boundary.
It forwards exact body bytes over one inherited AF_UNIX stream, never credentials, headers or
an upstream URL. Only a bounded normalized text or fixed unknown/failure
reply crosses back, and the frontend constructs its own bounded SSE envelope.
The future host broker must independently validate the complete request,
exact Run/input policy, output-token ceiling, durable journal and live Stop
fence before submission. This transport alone grants none of that authority.

Child output is drained incrementally with a combined 512 KiB ceiling and
absolute wall. Scanner warnings remain inert; malformed JSON objects and
duplicate terminal results fail. Success requires one matching zero-exit
terminal result, exact agreement with broker-normalized text, frontend and
bootstrap exits, and verified scope emptiness. The frontend writes only the
fixed completion.txt name; the host retains a read-only, quota-verified tmpfs
export directory descriptor after worker exit. No model-prose path is opened.
The text/export is private component evidence, not generated-output
registration, producing-Run provenance or owner Apply authority.

Test on the actual Linux host with synthetic runtimes and unchanged official
Hermes through a fake broker, including native image-byte equality, unrelated
path and network denial, immutable inputs, quotas, nested userns refusal,
detached descendants, Stop, ambiguous handoff, bounded output, malformed
reply/terminal rejection and post-exit export readback. No live provider,
credential, owner configuration, Kanban mutation or execution guard change.
Obtain two independent reviews, repair findings, then publish a full PR.

Final actual Linux namespace/scope group: all 32 tests pass, with no skips.
This includes unchanged official 0.21.5, one fake inference completion,
zero declared tools, exactly matching native image bytes and terminal/export
readback. Windows executes eleven portable contracts and skips 21 Linux-only
checks. Independent reviewers found the deadline acceptance race, missing
handoff limit re-read and ancillary ordering leak; all were repaired with
controlled clock, changed-limit and transferred-FD regression checks. Both
final independent reviews are clear. Real namespace Stop also exposed ENODEV
during held cgroup removal; the correction requires the original inactive
invocation and cgroup2 readback and has both negative and actual Linux tests.
Final wheel/sdist builds pass exact public-member and RECORD verification;
the installed wheel imports the namespace, frontend and scope handoff. The
slice also carries the separately twice-reviewed Caddy queued-heartbeat
fixture repair; all 13 portable Caddy fixture tests pass without changing its
original drain deadline or weakening exact close/EOF acceptance.
The final image-request admission correction requires exact text/list message
shapes and exact native-image parts, MIME and byte digest. Nine denial cases
cover hidden/alternate image fields, missing, changed, duplicate, external and
unprepared images. A recognized caption or dropped-image request cannot pass
this wire check; the qualified host broker must still validate independently.
The first image-delta review caught alternate image-bearing part shapes; the
fixed allowlist and exact MIME correction passed both independent final
re-reviews. Final artifacts were rebuilt after that correction and the
installed frontend bytes match the reviewed source exactly.
