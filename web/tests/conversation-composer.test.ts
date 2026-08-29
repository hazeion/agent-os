import assert from "node:assert/strict";
import test from "node:test";

import {
  commandSuggestions,
  conversationComposerIntent,
  validComposerCommandSource,
  validConversationComposerText,
} from "../src/lib/conversation-composer.ts";

test("composer keeps every leading slash inside the fixed command boundary", () => {
  assert.deepEqual(conversationComposerIntent("/steer focus here"), { argument: "focus here", command: "/steer", kind: "command", source: "/steer focus here" });
  assert.deepEqual(conversationComposerIntent("  /steer focus here"), { argument: "focus here", command: "/steer", kind: "command", source: "  /steer focus here" });
  assert.deepEqual(conversationComposerIntent("/model gpt-5"), { argument: "gpt-5", command: "/model", kind: "command", source: "/model gpt-5" });
  assert.deepEqual(conversationComposerIntent("/new"), { argument: "", command: "/new", kind: "command", source: "/new" });
  assert.deepEqual(conversationComposerIntent("/help"), { argument: "", command: "/help", kind: "command", source: "/help" });
  assert.deepEqual(conversationComposerIntent("/steer"), { command: "/steer", kind: "invalid_command", reason: "usage", source: "/steer" });
  assert.deepEqual(conversationComposerIntent("/help now"), { command: "/help", kind: "invalid_command", reason: "usage", source: "/help now" });
  assert.deepEqual(conversationComposerIntent("/unknown do not send"), { command: "/unknown", kind: "invalid_command", reason: "unknown", source: "/unknown do not send" });
  assert.deepEqual(conversationComposerIntent("/steering is ordinary"), { command: "/steering", kind: "invalid_command", reason: "unknown", source: "/steering is ordinary" });
  assert.deepEqual(conversationComposerIntent("Explain /steer here"), { kind: "turn", text: "Explain /steer here" });
  assert.deepEqual(conversationComposerIntent("Send this prompt "), { kind: "turn", text: "Send this prompt" });
});

test("completion stays local, ordered, and capped at the four reviewed commands", () => {
  const definitions = [
    { command: "/model", description: "Models", arguments: [{ required: false }] },
    { command: "/new", description: "New", arguments: [] },
    { command: "/steer", description: "Steer", arguments: [{ required: true }] },
    { command: "/help", description: "Help", arguments: [] },
    { command: "/unsafe", description: "Ignored", arguments: [] },
  ];
  assert.deepEqual(commandSuggestions("/", definitions).map((item) => item.command), ["/model", "/new", "/steer", "/help"]);
  assert.deepEqual(commandSuggestions("/m", definitions), [{ command: "/model", completion: "/model ", description: "Refresh or stage the next-Run model" }]);
  assert.deepEqual(commandSuggestions("/model ", definitions), []);
  assert.deepEqual(commandSuggestions("text", definitions), []);
});

test("composer text validation uses the exact public Turn boundary", () => {
  assert.equal(validConversationComposerText("valid"), true);
  assert.equal(validConversationComposerText(""), false);
  assert.equal(validConversationComposerText(" leading"), false);
  assert.equal(validConversationComposerText("trailing "), false);
  assert.equal(validConversationComposerText("x\0y"), false);
  assert.equal(validConversationComposerText("😀".repeat(6_000)), true);
  assert.equal(validConversationComposerText("😀".repeat(6_001)), false);
  assert.equal(validComposerCommandSource("/help"), true);
  assert.equal(validComposerCommandSource("/help "), true);
  assert.equal(validComposerCommandSource("/" + "😀".repeat(5_999)), true);
  assert.equal(validComposerCommandSource("/" + "😀".repeat(6_000)), false);
});
