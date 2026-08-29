import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
  url: "http://127.0.0.1:8890",
});
for (const name of ["document", "HTMLElement", "Node", "navigator", "window"] as const) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });

const { cleanup, render, screen } = await import("@testing-library/react");
const { TranscriptContent } = await import("../src/app/transcript-content.tsx");
const { safePublicHttpsDisplayHref, TranscriptLinkPreviews } = await import("../src/app/transcript-link-previews.tsx");

afterEach(() => cleanup());

test("creates only narrow public HTTPS display anchors with external-navigation protections", () => {
  render(<TranscriptContent content={[
    "Public https://docs.python.org/3/library/urllib.parse.html?view=1#url-parsing-security.",
    ["Not linked http://example.com https://localhost/admin https://127.0.0.1/private ", "https://", "user:pass@", "example.com/ https://example.com:8443/x."].join(""),
  ].join("\n")} />);

  const link = screen.getByRole("link");
  assert.equal(link.textContent, "https://docs.python.org/3/library/urllib.parse.html?view=1#url-parsing-security");
  assert.equal(link.getAttribute("target"), "_blank");
  assert.equal(link.getAttribute("rel"), "noopener noreferrer");
  assert.equal(link.getAttribute("referrerpolicy"), "no-referrer");
  assert.equal(document.querySelectorAll("a").length, 1);
  assert.match(document.querySelector(".transcript-markdown")?.textContent ?? "", /https:\/\/localhost\/admin/u);
});

test("keeps URLs inside inline code inert and supports links in bounded plain rendering", () => {
  const { rerender } = render(<TranscriptContent content="`https://example.com/code` and **https://www.example.org/strong**" />);
  assert.equal(document.querySelectorAll("a").length, 1);
  assert.equal(screen.getByRole("link").textContent, "https://www.example.org/strong");

  rerender(<TranscriptContent content="Visit https://www.example.org/plain" forcePlainText />);
  assert.equal(screen.getByRole("link").textContent, "https://www.example.org/plain");
});

test("uses the exact backend Message projection to keep approved IDN and public IP links clickable", () => {
  render(<TranscriptContent
    content="IDN https://bücher.de/path public https://8.8.8.8/dns blocked https://127.0.0.1/admin"
    linkPreviews={[
      { candidateOrdinal: 1, status: "unavailable" },
      { candidateOrdinal: 2, status: "disabled" },
      { candidateOrdinal: 3, status: "blocked" },
    ]}
    showLinkPreviewCards={false}
  />);

  const links = screen.getAllByRole("link");
  assert.deepEqual(links.map((link) => link.textContent), ["https://bücher.de/path", "https://8.8.8.8/dns"]);
  assert.equal(links.every((link) => link.getAttribute("rel") === "noopener noreferrer"), true);
  assert.match(document.querySelector(".transcript-markdown")?.textContent ?? "", /https:\/\/127\.0\.0\.1\/admin/u);
});

test("keeps backend approval aligned after duplicate fragment variants", () => {
  render(<TranscriptContent
    content="First https://python.org/x#one duplicate https://python.org/x#two IDN https://bücher.de/path"
    linkPreviews={[
      { candidateOrdinal: 1, status: "ready", title: "Python" },
      { candidateOrdinal: 3, status: "unavailable" },
    ]}
    showLinkPreviewCards={false}
  />);

  assert.deepEqual(screen.getAllByRole("link").map((link) => link.textContent), [
    "https://python.org/x#one",
    "https://python.org/x#two",
    "https://bücher.de/path",
  ]);
});

test("renders every static preview state while leaving the original link in place", () => {
  render(<TranscriptContent content="Read https://www.example.org/story" linkPreviews={[
    { candidateOrdinal: 1, displayHost: "www.example.org", status: "pending" },
    { candidateOrdinal: 2, displayHost: "www.example.org", status: "blocked" },
    { candidateOrdinal: 3, displayHost: "www.example.org", status: "disabled" },
  ]} />);

  assert.equal(screen.getByRole("link").textContent, "https://www.example.org/story");
  assert.equal(screen.getByText("Preview loading").textContent, "Preview loading");
  assert.equal(screen.getByText("Preview blocked for safety").textContent, "Preview blocked for safety");
  assert.equal(screen.getByText("Rich link previews are off").textContent, "Rich link previews are off");
  assert.equal(screen.getAllByText("The original link remains available above.").length, 3);
  assert.equal(document.querySelector(".transcript-link-preview")?.getAttribute("aria-live"), "polite");
});

test("renders ready and unavailable cards from bounded text-safe fields", () => {
  const opaqueImageId = "a".repeat(24);
  render(<TranscriptLinkPreviews previews={[
    { candidateOrdinal: 2, displayHost: "www.example.org", status: "unavailable" },
    { candidateOrdinal: 1, description: "A <script>alert(1)</script> description", displayHost: "www.example.org", imageAlt: "Article image", imageId: opaqueImageId, status: "ready", title: "A <b>safe</b> title" },
  ]} />);

  const cards = Array.from(document.querySelectorAll(".transcript-link-preview"));
  assert.deepEqual(cards.map((card) => card.getAttribute("data-candidate-ordinal")), ["1", "2"]);
  assert.equal(screen.getByText("A <b>safe</b> title").tagName, "STRONG");
  assert.equal(document.querySelector("script"), null);
  assert.equal(document.querySelector("b"), null);
  assert.equal(screen.getByRole("img", { name: "Article image" }).getAttribute("src"), `/api/link-previews/images/${opaqueImageId}`);
  assert.equal(screen.getByText("Preview unavailable").textContent, "Preview unavailable");
});

test("renders a canonical IPv6 display host without changing it", () => {
  render(<TranscriptLinkPreviews previews={[
    { candidateOrdinal: 1, displayHost: "2606:4700:4700::1111", status: "ready", title: "DNS" },
  ]} />);
  assert.equal(screen.getByText("2606:4700:4700::1111").textContent, "2606:4700:4700::1111");
});

test("drops invalid, duplicate, and excess projections without creating remote images", () => {
  render(<TranscriptLinkPreviews previews={[
    { candidateOrdinal: 0, status: "ready", title: "bad ordinal" },
    { candidateOrdinal: 1, imageId: "https://tracker.example/pixel", status: "ready", title: "First" },
    { candidateOrdinal: 1, status: "blocked", title: "duplicate" },
    { candidateOrdinal: 4, status: "pending", title: "excess" },
  ]} />);

  assert.equal(document.querySelectorAll(".transcript-link-preview").length, 1);
  assert.equal(screen.getByText("First").textContent, "First");
  assert.equal(document.querySelector("img"), null);
  assert.equal(document.querySelector("a"), null);
});

test("preserves a long valid backend host exactly and rejects over-limit text", () => {
  const longValid = `${"a".repeat(63)}.${"b".repeat(63)}.${"c".repeat(63)}.example.org`;
  const overlong = `${longValid}.${"d".repeat(63)}`;
  render(<TranscriptLinkPreviews previews={[
    { candidateOrdinal: 1, displayHost: longValid, status: "ready", title: "Long" },
    { candidateOrdinal: 2, displayHost: overlong, status: "ready", title: "Overlong" },
  ]} />);
  assert.equal(screen.getByText(longValid).textContent, longValid);
  assert.equal(document.body.textContent?.includes(overlong), false);
});

test("display validator fails closed for malformed and special-use destinations", () => {
  assert.equal(safePublicHttpsDisplayHref("https://example.com/path"), "https://example.com/path");
  for (const value of [
    "https://example.com:444/path",
    "https://example.com\\@127.0.0.1/",
    "https://[2001:db8::1]/",
    "https://10.0.0.1/",
    "https://host.home.arpa/",
    "https://example.test/",
    "https://example.com/%zz",
    "https://%65xample.com/",
    "https://example.com/%5clocal",
  ]) assert.equal(safePublicHttpsDisplayHref(value), null, value);
});

test("candidate trimming preserves balanced delimiters and removes unmatched closers", () => {
  render(<TranscriptContent content={[
    "https://example.org/a(b)",
    "https://example.org/a[b]",
    "https://example.org/a{b}",
    "https://example.org/a)))",
  ].join(" ")} />);
  assert.deepEqual(screen.getAllByRole("link").map((link) => link.textContent), [
    "https://example.org/a(b)",
    "https://example.org/a[b]",
    "https://example.org/a{b}",
    "https://example.org/a",
  ]);
});
