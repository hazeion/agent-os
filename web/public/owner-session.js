/** @returns {string | null} */
export function ownerCsrf() {
  if (typeof document === "undefined") return null;
  const matches = String(document.cookie ?? "").split(";").map(value => value.trim()).filter(value => value.startsWith("__Host-mentat-csrf="));
  if (matches.length !== 1) return null;
  const value = matches[0].slice("__Host-mentat-csrf=".length);
  return /^[A-Za-z0-9_-]{43}$/.test(value) ? value : null;
}

export function expireOwnerSession() {
  if (typeof window === "undefined" || window.location.pathname === "/sign-in") return;
  const message = document.createElement("main");
  message.textContent = "Returning to sign-in…";
  document.body.replaceChildren(message);
  window.location.replace("/sign-in?status=session-ended");
}

/** @param {RequestInfo | URL} input @param {RequestInit} [init] @returns {Promise<Response>} */
export async function ownerFetch(input, init = {}) {
  let options = init;
  let protectedRequest = false;
  if (typeof window !== "undefined") {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.origin);
    const sameApi = url.origin === window.location.origin && url.pathname.startsWith("/api/");
    const csrf = ownerCsrf();
    protectedRequest = sameApi && (Boolean(csrf) || document.documentElement.dataset.gatewayMode === "owner" || url.pathname === "/api/auth/session");
    const requestLike = typeof Request !== "undefined" && input instanceof Request;
    const method = (init.method ?? (requestLike ? input.method : "GET")).toUpperCase();
    if (sameApi && csrf && !["GET", "HEAD", "OPTIONS"].includes(method)) {
      const headers = new Headers(init.headers ?? (requestLike ? input.headers : undefined));
      headers.set("X-Mentat-Csrf", csrf);
      options = { ...init, headers };
    }
  }
  const response = await fetch(input, options);
  if (protectedRequest && response.status === 401) expireOwnerSession();
  return response;
}
