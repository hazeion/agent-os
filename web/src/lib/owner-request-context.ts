import { AsyncLocalStorage } from "node:async_hooks";

export type OwnerRequestContext = Readonly<{ cookie: string; csrf: string | null; lease?: string }>;
const context = new AsyncLocalStorage<OwnerRequestContext>();

export function runWithOwnerContext<T>(value: OwnerRequestContext, action: () => T): T {
  return context.run(Object.freeze(value), action);
}

export function currentOwnerContext(): OwnerRequestContext | undefined { return context.getStore(); }

/** Only validated server context becomes private bridge authentication headers. */
export function ownerBridgeHeaders(): Record<string, string> {
  const current = context.getStore();
  if (!current) return {};
  return {
    "X-Mentat-Owner-Session": current.cookie,
    ...(current.csrf ? { "X-Mentat-Owner-Csrf": current.csrf } : {}),
    ...(current.lease ? { "X-Mentat-Owner-Lease": current.lease } : {}),
  };
}
