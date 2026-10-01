import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: origin, pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { act, cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { HomeInboxAttention } = await import("../src/app/home-inbox-attention.tsx");
const originalFetch = globalThis.fetch;
const originalSetInterval = window.setInterval, originalClearInterval = window.clearInterval;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; Object.defineProperty(window, "setInterval", { configurable: true, value: originalSetInterval }); Object.defineProperty(window, "clearInterval", { configurable: true, value: originalClearInterval }); Object.defineProperty(document, "hidden", { configurable: true, value: false }); });
const itemId = (digit: string) => `inbox_item_${digit.repeat(32)}`;
const item = (digit: string, state = "needs_review") => ({ id: itemId(digit), kind: "result_review", revision: 1, created_at: 1790035200 - Number(digit), unread: true,
  acknowledged: false, state, title: `Review Garage ${digit} results` });
const page = (items: ReturnType<typeof item>[], count = items.length) => ({ items, next_cursor: null, counts: { needs_me: count, unread: count, all: count } });

test("Home shows server-wide Inbox count and only three exact item links", async () => {
  const calls: Array<{ path: string; method: string }> = [];
  globalThis.fetch = async (input, init) => { const url = new URL(String(input), origin); calls.push({ path: url.pathname + url.search, method: init?.method ?? "GET" });
    return Response.json(page([item("1"), item("2"), item("3")], 7)); };
  render(<HomeInboxAttention />);
  await screen.findByRole("heading", { name: "Needs your review · 7" });
  const links = screen.getAllByRole("link", { name: /Review Garage/u });
  assert.equal(links.length, 3);
  assert.deepEqual(links.map((link) => link.getAttribute("href")), ["1", "2", "3"].map((digit) => `/inbox?item=${itemId(digit)}`));
  assert.deepEqual(calls, [{ path: "/api/inbox?view=needs_me", method: "GET" }]);
});

test("Home keeps honest empty and unavailable states with a safe Inbox entry", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; if (calls === 1) return Response.json(page([])); throw new Error("offline"); };
  render(<HomeInboxAttention />);
  await screen.findByText("No Inbox review items right now.");
  fireEvent.click(screen.getByRole("button", { name: "Refresh Inbox attention" }));
  await screen.findByText("Inbox could not refresh. Last checked items are shown.");
  assert.ok(screen.getByRole("heading", { name: "Last checked Inbox · 0" }));
  assert.equal(screen.getByRole("link", { name: "Open Inbox" }).getAttribute("href"), "/inbox");
  cleanup();
  globalThis.fetch = async () => { throw new Error("offline"); };
  render(<HomeInboxAttention />);
  await screen.findByText("Inbox attention is temporarily unavailable.");
});

test("visible polling is bounded, non-overlapping, and removed on unmount", async () => {
  let calls = 0, releaseFirst: (() => void) | null = null, cleared = false;
  const ticks: Array<() => void> = [];
  Object.defineProperty(window, "setInterval", { configurable: true, value: (callback: () => void) => { ticks.push(callback); return 7; } });
  Object.defineProperty(window, "clearInterval", { configurable: true, value: (id: number) => { assert.equal(id, 7); cleared = true; } });
  globalThis.fetch = async () => { calls++; if (calls === 1) await new Promise<void>((resolve) => { releaseFirst = resolve; }); return Response.json(page([item("1")], calls)); };
  const rendered = render(<HomeInboxAttention />);
  await waitFor(() => assert.equal(calls, 1));
  assert.equal(ticks.length, 1);
  await act(async () => { ticks[0](); }); assert.equal(calls, 1);
  await act(async () => { document.dispatchEvent(new dom.window.Event("visibilitychange")); });
  assert.equal(calls, 1);
  await act(async () => { releaseFirst!(); });
  await screen.findByRole("heading", { name: "Needs your review · 2" });
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  ticks[0](); assert.equal(calls, 2);
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  await act(async () => { document.dispatchEvent(new dom.window.Event("visibilitychange")); });
  await screen.findByRole("heading", { name: "Needs your review · 3" });
  rendered.unmount(); assert.equal(cleared, true);
  ticks[0](); document.dispatchEvent(new dom.window.Event("visibilitychange")); assert.equal(calls, 3);
});

test("unresolved stale Inbox item stays an inert navigation link", async () => {
  globalThis.fetch = async () => Response.json(page([item("1", "stale")]));
  render(<HomeInboxAttention />);
  await screen.findByText("Source changed · inspect in Inbox");
  assert.equal(screen.getByRole("link", { name: /Review Garage 1 results/u }).getAttribute("href"), `/inbox?item=${itemId("1")}`);
});

test("a late response from an unmounted Home card cannot replace fresh attention", async () => {
  let calls = 0, releaseOld: (() => void) | null = null;
  globalThis.fetch = async () => { calls++; if (calls === 1) await new Promise<void>((resolve) => { releaseOld = resolve; });
    return Response.json(page([item("1")], calls)); };
  const old = render(<HomeInboxAttention />);
  await waitFor(() => assert.equal(calls, 1));
  old.unmount();
  render(<HomeInboxAttention />);
  await screen.findByRole("heading", { name: "Needs your review · 2" });
  await act(async () => { releaseOld!(); });
  assert.ok(screen.getByRole("heading", { name: "Needs your review · 2" }));
});

test("a background poll keeps a focused Inbox link mounted until fresh results arrive", async () => {
  let calls = 0, releaseSecond: (() => void) | null = null;
  const ticks: Array<() => void> = [];
  Object.defineProperty(window, "setInterval", { configurable: true, value: (callback: () => void) => { ticks.push(callback); return 7; } });
  globalThis.fetch = async () => { calls++; if (calls === 2) await new Promise<void>((resolve) => { releaseSecond = resolve; }); return Response.json(page([item("1")], calls)); };
  render(<HomeInboxAttention />);
  const link = await screen.findByRole("link", { name: /Review Garage 1 results/u });
  link.focus();
  await act(async () => { ticks[0](); });
  await waitFor(() => assert.equal(calls, 2));
  assert.equal(document.activeElement, link);
  assert.ok(screen.getByText("Checking…"));
  assert.equal(screen.queryByText("Checking Inbox…"), null);
  await act(async () => { releaseSecond!(); });
  await screen.findByRole("heading", { name: "Needs your review · 2" });
  assert.equal(document.activeElement, link);
});

test("a read completed while hidden allows one fresh read on return", async () => {
  let calls = 0, releaseFirst: (() => void) | null = null;
  globalThis.fetch = async () => { calls++; if (calls === 1) await new Promise<void>((resolve) => { releaseFirst = resolve; });
    return Response.json(page([item("1")], calls)); };
  render(<HomeInboxAttention />);
  await waitFor(() => assert.equal(calls, 1));
  await act(async () => { document.dispatchEvent(new dom.window.Event("visibilitychange")); });
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  await act(async () => { releaseFirst!(); });
  assert.equal(calls, 1);
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  await act(async () => { document.dispatchEvent(new dom.window.Event("visibilitychange")); });
  await screen.findByRole("heading", { name: "Needs your review · 2" });
  assert.equal(calls, 2);
});
