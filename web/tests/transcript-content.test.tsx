import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
  url: "http://127.0.0.1:8890",
});
for (const name of ["document", "HTMLElement", "KeyboardEvent", "MouseEvent", "Node", "navigator", "window"] as const) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });

const { cleanup, render, screen } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { TranscriptContent, transcriptContentLimits } = await import("../src/app/transcript-content.tsx");

afterEach(() => cleanup());

test("renders a limited Markdown hierarchy without creating links or HTML", () => {
  render(<TranscriptContent content={[
    "# Result",
    "",
    "A **strong** result with *emphasis*, `inline code`, and https://example.test.",
    "",
    "> Quoted evidence",
    "",
    "- First",
    "- Second",
    "",
    "1. Ordered",
  ].join("\n")} />);

  assert.equal(screen.getByRole("heading", { level: 2, name: "Result" }).textContent, "Result");
  assert.equal(document.querySelector("strong")?.textContent, "strong");
  assert.equal(document.querySelector("em")?.textContent, "emphasis");
  assert.equal(document.querySelector("blockquote")?.textContent, "Quoted evidence");
  assert.deepEqual(Array.from(document.querySelectorAll("li"), (item) => item.textContent), ["First", "Second", "Ordered"]);
  assert.equal(document.querySelector("a"), null);
});

test("renders hostile HTML as inert escaped text", () => {
  const hostile = '<script>globalThis.pwned = true</script><img src=x onerror="alert(1)"><button>Run me</button>';
  render(<TranscriptContent content={hostile} />);

  assert.equal(document.querySelector("script"), null);
  assert.equal(document.querySelector("img"), null);
  assert.equal(document.querySelector(".transcript-markdown button"), null);
  assert.match(document.querySelector(".transcript-markdown")?.textContent ?? "", /<script>/u);
  assert.equal((globalThis as { pwned?: boolean }).pwned, undefined);
});

test("renders inert highlighted fenced code and copies the code text", async () => {
  const copied: string[] = [];
  const user = userEvent.setup({ document: dom.window.document });
  render(<TranscriptContent content={'```ts\nconst answer = "<unsafe>";\n// no execution\n```'} copyText={async (value) => { copied.push(value); }} />);

  const code = screen.getByLabelText("TypeScript code block 1");
  assert.equal(code.getAttribute("tabindex"), "0");
  assert.equal(code.querySelector(".transcript-token-keyword")?.textContent, "const");
  assert.equal(code.querySelector(".transcript-token-string")?.textContent, '"<unsafe>"');
  assert.equal(code.querySelector("unsafe"), null);

  const copy = screen.getByRole("button", { name: "Copy TypeScript code block 1" });
  copy.focus();
  await user.keyboard("{Enter}");
  assert.deepEqual(copied, ['const answer = "<unsafe>";\n// no execution']);
  assert.equal(document.activeElement, copy);
  assert.equal(screen.getByRole("status").textContent, "Code copied.");
});

test("replaces bidi controls in rendered and copied content", async () => {
  const copied: string[] = [];
  const user = userEvent.setup({ document: dom.window.document });
  render(<TranscriptContent content={"safe\u202Etxt.exe\u2066 end"} copyText={async (value) => { copied.push(value); }} />);

  const rendered = document.querySelector(".transcript-markdown")?.textContent ?? "";
  assert.equal(/[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(rendered), false);
  assert.match(rendered, /safe�txt\.exe� end/u);
  await user.click(screen.getByRole("button", { name: "Copy message" }));
  assert.equal(/[\u202e\u2066]/u.test(copied[0]), false);
});

test("bounds oversized display content and marks truncation", () => {
  const content = "x".repeat(transcriptContentLimits.maximumDisplayCodePoints + 50);
  render(<TranscriptContent content={content} />);

  assert.equal(document.querySelector(".transcript-markdown")?.textContent?.length, transcriptContentLimits.maximumDisplayCodePoints);
  assert.equal(screen.getByRole("note").textContent, "Content truncated for safe display.");
});

test("falls back to bounded plain text for structurally amplified Markdown", () => {
  const fragmented = Array.from({ length: transcriptContentLimits.maximumRenderUnits }, (_, index) => `- **item ${index}**`).join("\n");
  render(<div>{Array.from({ length: 200 }, (_, index) => <TranscriptContent content={fragmented} key={index} messageLabel={`message ${index}`} />)}</div>);

  assert.equal(document.querySelectorAll(".transcript-content").length, 200);
  assert.equal(document.querySelectorAll(".transcript-markdown li").length, 0);
  assert.equal(screen.getAllByRole("note").length, 200);
  assert.equal(screen.getAllByText("Formatting simplified for safe display.").length, 200);
});

test("exposes scrollable code semantics and keeps copy failure concise", async () => {
  const user = userEvent.setup({ document: dom.window.document });
  render(<TranscriptContent content={`\`\`\`\n${"long-token".repeat(200)}\n\`\`\``} copyText={async () => { throw new Error("denied"); }} messageLabel="assistant message" />);

  assert.equal(screen.getByLabelText("Plain text code block 1").getAttribute("dir"), "ltr");
  await user.click(screen.getByRole("button", { name: "Copy assistant message" }));
  assert.equal(screen.getByRole("status").textContent, "Message could not be copied.");
});
