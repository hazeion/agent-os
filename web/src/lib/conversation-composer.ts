export const MENTAT_COMMANDS = ["/model", "/new", "/steer", "/help"] as const;

export type MentatCommand = typeof MENTAT_COMMANDS[number];

export const MENTAT_COMMAND_DESCRIPTIONS: Readonly<Record<MentatCommand, string>> = {
  "/model": "Refresh or stage the next-Run model",
  "/new": "Start a new Conversation",
  "/steer": "Guide the active Run",
  "/help": "Show Mentat commands",
};

export type ConversationComposerIntent =
  | { kind: "turn"; text: string }
  | { kind: "command"; command: MentatCommand; argument: string; source: string }
  | { kind: "invalid_command"; command: string; reason: "unknown" | "usage"; source: string };

export type CommandSuggestion = {
  command: MentatCommand;
  description: string;
  completion: string;
};

type CommandDefinition = Readonly<{
  command: string;
  description: string;
  arguments: ReadonlyArray<Readonly<{ required: boolean }>>;
}>;

/** Parse only the four project-owned commands. Any leading slash stays a command. */
export function conversationComposerIntent(value: string): ConversationComposerIntent {
  const commandSource = value.startsWith("/")
    ? value
    : /^\s+\/steer(?:\s|$)/u.test(value) ? value.trimStart() : null;
  if (commandSource === null) return { kind: "turn", text: value.trimEnd() };
  const match = /^(\/[^\s]*)(?:\s+([\s\S]*))?$/u.exec(commandSource);
  const command = match?.[1] ?? value;
  const argument = (match?.[2] ?? "").trim();
  if (!MENTAT_COMMANDS.includes(command as MentatCommand)) {
    return { kind: "invalid_command", command, reason: "unknown", source: value };
  }
  const exact = command as MentatCommand;
  const usageInvalid = (exact === "/new" || exact === "/help") && argument.length > 0
    || exact === "/steer" && argument.length === 0;
  if (usageInvalid) return { kind: "invalid_command", command, reason: "usage", source: value };
  return { kind: "command", command: exact, argument, source: value };
}

/** Return local, prefix-only completion candidates. This function performs no I/O. */
export function commandSuggestions(
  value: string,
  definitions: readonly CommandDefinition[],
): CommandSuggestion[] {
  if (!/^\/[^\s]*$/u.test(value)) return [];
  const known = new Map(definitions.map((definition) => [definition.command, definition]));
  return MENTAT_COMMANDS
    .filter((command) => command.startsWith(value) && known.has(command))
    .slice(0, 4)
    .map((command) => {
      const definition = known.get(command)!;
      return {
        command,
        description: MENTAT_COMMAND_DESCRIPTIONS[command],
        completion: definition.arguments.length > 0 ? `${command} ` : command,
      };
    });
}

export function validConversationComposerText(value: string): boolean {
  return value.length > 0
    && value.trim() === value
    && Array.from(value).length <= 6_000
    && !value.includes("\0");
}

export function validComposerCommandSource(value: string): boolean {
  return (value.startsWith("/") || /^\s+\/steer(?:\s|$)/u.test(value))
    && Array.from(value).length <= 6_000
    && !value.includes("\0");
}
