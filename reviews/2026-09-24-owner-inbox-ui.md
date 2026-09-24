# Owner Inbox website and exact result-review opening

Status: design and implementation reviewed by two independent agents for the website slice of
[#240](https://github.com/hazeion/agent-os/issues/240).

The Inbox is one owner-authenticated Emerald route with Needs me, Unread and
All views. Needs me includes every unresolved item, even when acknowledged;
Unread includes every item without a read receipt, including resolved items;
All includes every retained item. Each view sorts by item creation time then
opaque ID, newest first. Changing views resets the cursor. A fixed 50-item page uses an opaque last-item cursor and returns
bounded counts. A changed or pruned cursor requests a refresh; it never falls
back to an unbounded list. An item has only a server-derived title, status,
created time, read/ack state and opaque ID. Opening may call the exact Read
operation; an explicit Acknowledge uses the current item revision and cannot
resolve the source or approve work. A lost mark response refreshes the item
before another attempt; the backend's receipt handles an exact duplicate.

`/inbox?item=<opaque-id>` is the shareable owner deep link. It never contains
a Project ID, source URL, runtime reference or action token. A fixed Python
`open` capability reads that item, proves current Project incarnation and the
ordered three exact saved heads and pending decision state, then obtains the
existing safe deliverable projection and rechecks both heads and item/source
decision state before returning it. A change
between reads yields `stale`, with no other Project selected. The browser
focuses the `Review Project results` heading after the exact content loads.

The item-bound `status`, `preview` and `confirm` capabilities accept only the
opaque item ID and the existing bounded owner action fields. Python proves
current incarnation/heads before calling the existing review authority. A
preview returned by that authority is compared to the item's three heads
before display. Confirmation checks the Inbox item, source incarnation,
ordered heads and confirmation receipt inside the same source review
transaction, including its duplicate path. A repeated response returns only
the prior decision for that same item/generation/action; it cannot confirm a
new Project after ID reuse. The browser compares the exact preview heads against the displayed
safe content, retains an uncertain preview for explicit retry, and refreshes
the item/list after a verified decision. Inbox actions neither mutate Tasks
nor dispatch Agents.

An archived or paused Project shows `activation_required` and closes review
controls. The owner can navigate to Projects & Tasks to use supported lifecycle
controls; the Inbox does not invent a paused-Project activation route. A
deleted/reused or replaced generation shows a safe stale/retained detail with
Refresh, Back and exact-revision Acknowledge; review controls stay closed.
Stale status is announced in a live region, and Back restores focus to the
originating item when still present. A post-action refresh resets a loaded
older page to the canonical first page with a visible announcement; Back then
focuses the list heading until the owner loads older items again. Resolved
items show the exact three
immutable versions from their original Project incarnation and cannot start a
new review from the old item. The Project page
remains available for ordinary direct navigation, separate from the exact
Inbox review path.

The page reuses the existing safe result renderer and presents all three
saved contents before offering Accept or Request changes. The former binds
the whole bundle; the latter names affected slots and a bounded note. Product
links keep the existing HTTPS validation and external-navigation protections.
Images use only the existing version-bound private preview route. Browser
notifications remain optional and are never requested while merely opening
the Inbox. Home can show a capped navigation count after this route is sound.

The Node gateway lists only fixed same-origin owner-session GETs and
CSRF-protected mutations. Python owns SQLite and all source binding. Strict
contracts reject extra fields, private incarnations and oversized content at
both bridge and browser boundaries. Tests cover two-device read/ack races,
lost responses, change between list/open/preview/confirm, Project ID reuse,
non-active Project, stale pagination, keyboard focus and mobile overflow. Run
the affected Python, website, production build and built desktop/mobile
review journey, then two independent read-only code reviews before a full PR.

## Implementation evidence

Python adds fixed owner-bound page/open/preview/confirm operations to the
schema-34 Inbox authority. Page cursors and counts are bounded; opening
rechecks the pending decision after reading the exact three current contents.
For resolved, non-active or reused Project IDs, it serves only the three
immutable versions tied to the item's original incarnation. Item-bound
confirmation checks the source and the durable duplicate receipt inside the
same Project review transaction. The Node gateway has five manifest-listed,
same-origin owner-session routes, with CSRF on mutations and strict private
bridge/browser projections. The Emerald Inbox page presents all three contents
before review actions, maintains separate Read/Acknowledge state, and keeps
an uncertain confirmation for exact explicit retry.

Two independent design reviews found and closed the duplicate-confirmation
race, pending-decision read race, stale-item acknowledgment and pagination
semantics. Two independent read-only code reviews found and closed delayed
list/read ordering, retained-version access, confirmation/acknowledgment focus,
lost-ack list reconciliation and later-page cursor reset. Focused tests cover
these cases, Project ID reuse and hostile route/response input. The production
build and built desktop/mobile garage journey passed, including an exact Inbox
acceptance with no Agent Run. The affected Python suite passed 47 tests, the
website suite passed 475 tests, and ESLint/TypeScript passed. Desktop and
mobile Inbox screenshots were visually checked for overflow, result legibility
and compact controls. Existing Run failure/recovery producers, Home
attention count and coordinated revision routing remain outside this slice;
issue #240 stays open.

Hosted package and Node quality gates found one browser-smoke expectation
from the old four-item navigation: the sixth compact-height Tab now reaches
Inbox, with Runs seventh. The full smoke also needed to include Inbox as a
hydrated route. Both checks now cover the new route without removing prior
assertions. A strict local `compact-height` focus mode and explicit managed
browser no-sandbox opt-in allowed the exact 1024×320 keyboard/tooltip contract
to pass against a disposable loopback preview; the full local smoke passed
route inspection but stopped later in an unrelated planner fixture. Two
independent read-only reviews found no remaining issue with this correction.
Hosted full-smoke reruns remain required before merge.
