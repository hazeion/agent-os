# Home Inbox attention navigation

Status: design and implementation reviewed by two independent agents for a small UI slice of
[#240](https://github.com/hazeion/agent-os/issues/240).

Home's right activity rail shows the count of unresolved owner Inbox items and
up to three newest safe titles from the fixed `needs_me` page. Each title links
only to `/inbox?item=<opaque-id>`, so the Inbox revalidates the original source
before presenting a review. The rail never accepts results, acknowledges an
item, retries a Run, requests browser notification permission, or interprets
provider output. It makes no new data authority: schema 34 and the fixed Inbox
page remain canonical. Acknowledged-but-unresolved items still count as
needing the owner. The count is bounded by the server's 2,048-item ceiling.

The card loads once on Home mount and refreshes on an explicit owner action,
when a hidden tab becomes visible again, and at a fixed 30-second interval
while Home stays visible. The interval never overlaps an in-flight read, does
no network work while hidden, and is removed with the component. If a tab becomes visible during an
in-flight read, exactly one trailing read runs afterward. In-flight reads are
generation-bound so a late older response cannot replace newer attention.
Background refresh keeps verified links mounted and shows a quiet checking
hint; if the refresh fails, those links are marked as last-checked rather than
claimed current. Initial loading, empty and unavailable states retain an Inbox
link. Closing or collapsing the rail does not mutate work. An unresolved stale
item remains in Needs me as inert navigation, so the owner can inspect its
retained source or acknowledge it; a resolved item does not. The top-three list
does not imply that other Inbox kinds have been implemented; current backend
items are exact Project result reviews only.

Use the Emerald right-rail tokens, compact buttons and keyboard-selectable
links. Tests cover safe opaque links, all four states, an unresolved stale
item, 30-second foreground polling, hidden/unmount cleanup, non-overlapping
reads, updated count after visibility refresh, stale-response rejection, no
mutation calls and narrow layout. Run website tests/build and two independent read-only reviews before
a full PR. Run failure/unknown/recovery Inbox producers remain a separate
authority slice; this card cannot substitute for them.

## Implementation evidence

The Home right rail uses the fixed same-origin owner Inbox page and renders the
server's full unresolved count with at most three validated opaque item links.
Initial, empty, ready, stale-item and unavailable states are explicit. A
30-second visible-only timer, visibility return and manual Refresh use one
non-overlapping request. A visibility return during an in-flight read queues
one trailing check; hidden completion, unmount and older responses cannot
overwrite newer attention. Background reads keep focused links mounted, with
a quiet checking hint; a failed read labels the retained projection last
checked. Focused tests cover these transitions and all Home Console interactions.
The built garage journey checks the card and its exact Inbox link at desktop
and 390px mobile widths before owner result acceptance. All 482 website tests,
ESLint, TypeScript and the production build passed. The built desktop/mobile
walkthrough passed after removing a test-only assumption that the stacked
mobile rail needed an Expand control; both widths still check the live count
and exact item link, with a 44px mobile target.

Two independent design and two independent read-only code reviews found and
closed foreground-freshness, unresolved-stale contract, focus and trailing-read
issues. Run attention producers, coordinated revisions and notification
opt-in remain open under issue #240.
