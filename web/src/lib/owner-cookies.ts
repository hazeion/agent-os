export const OWNER_COOKIE = "__Host-mentat";
export const OWNER_CSRF_COOKIE = "__Host-mentat-csrf";
export const LOGIN_COOKIE = "__Host-mentat-login";

export function ownerCookie(header: string | null, name: string): string | null {
  if (!header || header.length > 8192) return null;
  const values = header.split(";").map(value => value.trim()).filter(value => value.startsWith(`${name}=`));
  if (values.length !== 1) return null;
  const value = values[0]!.slice(name.length + 1);
  return /^[A-Za-z0-9_-]{43}$/u.test(value) ? value : null;
}

export function sessionContext(request: Request, unsafe: boolean): { cookie: string; csrf: string | null } | null {
  const cookie = ownerCookie(request.headers.get("cookie"), OWNER_COOKIE);
  if (!cookie) return null;
  if (!unsafe) return { cookie, csrf: null };
  const csrf = ownerCookie(request.headers.get("cookie"), OWNER_CSRF_COOKIE);
  return csrf && request.headers.get("x-mentat-csrf") === csrf ? { cookie, csrf } : null;
}
