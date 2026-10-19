# Same-port restart preflight

Status: implemented and locally verified; independent review and actual app restart pending.

An owned local acceptance run completed Project/Task creation and readback,
verified stop, and confirmed the owned listener/state/children were gone.
Immediate same-port restart nevertheless failed `gateway_port_unavailable`.
The current probe binds a bare TCP socket. On POSIX, closed accepted
connections can leave TIME_WAIT while Node's normal SO_REUSEADDR socket can
already bind that same endpoint. Waiting is not a fix.

The bounded preflight must use SO_REUSEADDR on POSIX only, matching the
existing Node/libuv TCP behavior. It must never use SO_REUSEPORT or share an
active listener. Windows must retain its original default bind and must not
receive POSIX SO_REUSEADDR semantics. libuv's Windows implementation explicitly
avoids both SO_REUSEADDR, which can steal a port, and SO_EXCLUSIVEADDRUSE,
which can reject TIME_WAIT. The probe remains a
single short-lived socket, with no retry, substituted port, timeout change,
process inspection or listener termination. Existing loopback-only gateway
validation remains unchanged. This preflight is not a reservation across the
subsequent Node launch; ordinary bind races still fail without retry.

Regression strategy: an owned POSIX listener accepts one owned connection,
actively closes its accepted socket before the client, and completes closure
without sleeps. Require the old bare-bind probe to reject the TIME_WAIT
endpoint, then require the corrected probe to accept it. Separate real owned
IPv4/IPv6 listeners must remain unavailable. Portable mocked-socket checks
verify POSIX option selection/order, unchanged Windows options, bind failure and
context-managed cleanup. Full application restart remains an acceptance-worker
gate after two independent reviews; socket tests do not substitute for it.

Primary references: Python's
[socket.create_server documentation](https://docs.python.org/3/library/socket.html#socket.create_server)
describes POSIX SO_REUSEADDR and TIME_WAIT; libuv's
[Unix TCP implementation](https://github.com/libuv/libuv/blob/v1.x/src/unix/tcp.c)
sets SO_REUSEADDR before bind; the
[Windows TCP implementation](https://github.com/libuv/libuv/blob/v1.x/src/win/tcp.c)
explains why Windows sets neither reuse nor exclusive options. Microsoft's
[SO_EXCLUSIVEADDRUSE documentation](https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse)
documents the distinct Windows sharing semantics and exclusive-use behavior.

## Local verification

All 37 final web-runtime tests pass without skips on macOS, including the real owned
TIME_WAIT counterfactual and active IPv4/IPv6 listener refusal. The FIN exchange
is synchronized by EOF reads, with two-second bounds and no wait/retry. The
plain bind fails with EADDRINUSE immediately before two successful corrected
probes on the same port. Mocked Windows cases require the unchanged default
bind with no reuse or exclusive option. Option/bind failures still refuse.
Existing loopback-only and startup/shutdown tests remain unchanged and pass.
`git diff --check` passes.

The initial sandboxed three-socket attempt failed with EPERM before bind.
The subsequent approved host execution ran the complete module successfully;
the permission failure is not presented as a product failure or a passed test.
An initial local version added Windows exclusive setup. Although its 38 tests
passed, checking the actual libuv source showed that this could unnecessarily
reject TIME_WAIT. That version was removed before commit; its test result does
not stand in for final-source verification. Actual Linux and Windows socket
behavior has not been executed here. No owner
port was inspected, connected to or terminated. Full production app restart
must still be rerun by the acceptance worker after two independent reviews.
