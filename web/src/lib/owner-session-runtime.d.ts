declare module "*owner-session.js" {
  export const ownerFetch: typeof fetch;
  export function ownerCsrf(): string | null;
  export function expireOwnerSession(): void;
}
