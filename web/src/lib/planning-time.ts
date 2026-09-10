/** Reminder inputs are device-local; persisted timestamps remain exact instants. */
export function browserTimezone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; }
  catch { return "UTC"; }
}

export function planningTimestamp(value: string, timezone?: string, locale?: string): string {
  const instant = new Date(value);
  if (Number.isNaN(instant.valueOf())) return "Time unavailable";
  const fields: Intl.DateTimeFormatOptions = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" };
  try { return new Intl.DateTimeFormat(locale, { ...fields, timeZone: timezone ?? browserTimezone() }).format(instant); }
  catch { return new Intl.DateTimeFormat(locale, { ...fields, timeZone: "UTC" }).format(instant); }
}

export function inputTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "";
  return new Date(parsed.valueOf() - parsed.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function localInputTimestamp(value: string, originalInstant?: string, originalInput?: string): string {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$/u.test(value) || value.startsWith("0000")) return "";
  // The same wall time can represent two instants at the autumn transition.
  // An unchanged input preserves the original fold, seconds, and precision.
  if (originalInstant && inputTimestamp(originalInstant) && (originalInput ?? inputTimestamp(originalInstant)) === value) return originalInstant;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "";
  const instant = parsed.toISOString();
  // Date normalizes nonexistent spring-forward times and impossible dates.
  return inputTimestamp(instant) === value ? instant : "";
}
