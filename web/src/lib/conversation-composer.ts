export type ConversationComposerIntent =
  | { kind: "turn"; text: string }
  | { kind: "steer"; text: string };

/**
 * Recognize the one Home composer command without turning the composer into a
 * general command parser. Leading whitespace is ignored only for command
 * detection; ordinary Turn text remains byte-for-byte unchanged.
 */
export function conversationComposerIntent(value: string): ConversationComposerIntent {
  const commandCandidate = value.replace(/^\s+/u, "");
  if (!/^\/steer(?:\s|$)/u.test(commandCandidate)) {
    return { kind: "turn", text: value };
  }
  return { kind: "steer", text: commandCandidate.slice("/steer".length).trim() };
}

export function validConversationComposerText(value: string): boolean {
  return value.length > 0
    && value.trim() === value
    && Array.from(value).length <= 6_000
    && !value.includes("\0");
}
