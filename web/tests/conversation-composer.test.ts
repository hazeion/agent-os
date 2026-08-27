import assert from "node:assert/strict";
import test from "node:test";

import {
  conversationComposerIntent,
  validConversationComposerText,
} from "../src/lib/conversation-composer.ts";

test("composer recognizes only an exact leading steer command", () => {
  assert.deepEqual(conversationComposerIntent("/steer focus here"), { kind: "steer", text: "focus here" });
  assert.deepEqual(conversationComposerIntent("  \n/steer   focus here  "), { kind: "steer", text: "focus here" });
  assert.deepEqual(conversationComposerIntent("/steer\nuse the safer path"), { kind: "steer", text: "use the safer path" });
  assert.deepEqual(conversationComposerIntent("/steering is ordinary"), { kind: "turn", text: "/steering is ordinary" });
  assert.deepEqual(conversationComposerIntent("Explain /steer here"), { kind: "turn", text: "Explain /steer here" });
  assert.deepEqual(conversationComposerIntent(" /STEER no"), { kind: "turn", text: " /STEER no" });
});

test("composer text validation uses the exact public Turn boundary", () => {
  assert.equal(validConversationComposerText("valid"), true);
  assert.equal(validConversationComposerText(""), false);
  assert.equal(validConversationComposerText(" leading"), false);
  assert.equal(validConversationComposerText("trailing "), false);
  assert.equal(validConversationComposerText("x\0y"), false);
  assert.equal(validConversationComposerText("😀".repeat(6_000)), true);
  assert.equal(validConversationComposerText("😀".repeat(6_001)), false);
});
