# PR #292 submitted versus startup timeout fixture

Exact base: `d61f2593df97315cd3a8c9d2b05adb1274bfc2e5`.
Current macOS Python 3.11 job 109794223504 fails only the uncertainty assertion
in the real inert App Server timeout test. Its 0.2-second budget included
interpreter startup and handshake. Expiry before submission correctly has
certain evidence; that production distinction must remain unchanged.

The fixture now establishes its owned stdlib handshake under the existing
ordinary 1-second fixture startup budget, then retains the exact 0.2-second
request, timeout code and uncertain=True assertions. Close must also leave
the captured owned process terminal. A deterministic clock-seam regression
proves exhausted startup budget never submits and remains certain; the existing
end-to-end startup plus method budget test is unchanged. Production code,
deadlines, submission/retry/authority and ownership remain unchanged.

Qualification: full 47 methods pass on Windows Python 3.11.5 (45 pass, 2 POSIX
skips) and actual Linux Python 3.13.14 (46 pass, 1 Windows-only skip); 60 focused
repetition checks pass in 4.734 seconds. Both independent reviews are clear;
B independently reran the three affected/budget methods. Diffcheck is clean.
No installed Codex/provider/model, owner credentials, service or configuration
is used. The sole real child is the existing owned temporary stdlib protocol
fixture; finally-close precedes temporary-root cleanup. Hosted exact-head
acceptance remains pending after publication.
