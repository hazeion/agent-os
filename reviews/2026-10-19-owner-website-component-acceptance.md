# Owner website component acceptance

Tested code: repaired PR #259 head `211368c`, with Node 24.19.0,
Next 16.3.8, Python 3.13.14 and installed Chrome 155.0.8059.80 on macOS.
This is component evidence using intercepted provider traffic and disposable
private state, not live Google enrollment or Linux remote activation.

A fresh locked npm install reports zero vulnerabilities. The production
standalone website builds successfully. The initial targeted gate's HTTP and
browser skips are followed by these positive runs against the built website:

- The real HTTP/SSE test passes in 5.438 seconds. Revoking the owner session
  stops further disclosure on an open stream, does not extend idle expiry and
  releases the stream reservation.
- Both actual Chrome setup/website tests pass in 31.639 seconds without skips.
  They cover the terminal-bound setup proof and restrictive CSP, unauthenticated
  API refusal, wrong account, cancellation, expiry, unavailable provider,
  secure HttpOnly session cookies, separate browser contexts, CSRF refusal and
  sign-out behavior. Google-provider requests are intercepted, never sent.
- Generated sign-in screenshots were inspected at desktop and mobile viewport
  sizes. Text and the primary action remain readable without clipping or
  horizontal overflow. Screenshots remain ignored local QA artifacts.

Chrome is the installed version, not the separate pinned Lighthouse browser.
Separate browser contexts and mobile viewport simulation do not establish
physical-device or actual multi-device acceptance. No owner account,
credential store, provider consent, public host or production Run was used.
Current-head hosted checks, real operator configuration, independent human
remote-security acceptance and the complete Project journey remain required.
