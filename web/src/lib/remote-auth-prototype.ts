/**
 * Disposable MDA-1 proof only.  Nothing imports this module from the gateway,
 * launcher, or bridge.  It deliberately uses an in-memory fake bridge and
 * simplified WebAuthn evidence; it is not an authentication implementation.
 */
import { createHash, randomBytes as nodeRandomBytes, timingSafeEqual } from "node:crypto";

const BOOTSTRAP_WINDOW_MS = 10 * 60 * 1_000;
const CEREMONY_WINDOW_MS = 5 * 60 * 1_000;
const REAUTH_WINDOW_MS = 10 * 60 * 1_000;
const MAX_ACTIVE_CEREMONIES = 8;
const RECOVERY_CODE_COUNT = 10;
const MAX_RECOVERY_CODE_GENERATION_ATTEMPTS = RECOVERY_CODE_COUNT * 10;
const SESSION_IDLE_MS = 60 * 60 * 1_000;
const SESSION_ABSOLUTE_MS = 24 * 60 * 60 * 1_000;
const SESSION_COOKIE_NAME = "__Host-mentat-prototype";
const FORWARDED_HEADERS = new Set(["forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"]);
const DEVICE_ID = /^device_[A-Za-z0-9_-]{16,128}$/u;
const CEREMONY_ID = /^ceremony_[A-Za-z0-9_-]{16,128}$/u;
const CREDENTIAL_ID = /^[A-Za-z0-9_-]{16,512}$/u;

export class RemoteAuthPrototypeError extends Error {
  constructor(readonly code: "invalid_configuration" | "bootstrap_unavailable" | "bootstrap_invalid" | "ceremony_invalid" | "session_invalid" | "last_device") {
    super(code);
    this.name = "RemoteAuthPrototypeError";
  }
}

export type PrototypeRequest = Readonly<{
  method: string;
  path: string;
  headers?: Readonly<Record<string, string | undefined>>;
  body?: unknown;
}>;

export type PrototypeResponse = Readonly<{
  status: 200 | 400 | 401 | 403 | 404 | 405;
  body: Readonly<{ status: "ok" | "invalid" | "unauthenticated" | "forbidden" | "not_found" | "method_not_allowed" }>;
  headers: Readonly<{ "Cache-Control": "no-store" }>;
}>;

export type PrototypeBridgeCapability = "prototype.fixed_read" | "prototype.fixed_mutation";
export type PrototypeFakeBridge = Readonly<{ call(capability: PrototypeBridgeCapability): void }>;

export type PrototypeBridgeInspector = PrototypeFakeBridge & Readonly<{ calls(): readonly PrototypeBridgeCapability[] }>;

export function createInMemoryPrototypeBridge(): PrototypeBridgeInspector {
  const invoked: PrototypeBridgeCapability[] = [];
  return Object.freeze({
    call(capability: PrototypeBridgeCapability): void { invoked.push(capability); },
    calls(): readonly PrototypeBridgeCapability[] { return [...invoked]; },
  });
}

type RandomBytes = (size: number) => Uint8Array;
type Clock = () => number;

type Bootstrap = { codeHash: string; expiresAt: number };
type Device = { id: string; credentialHash: string; label: string; revision: number; createdAt: number; lastCounter: number; revokedAt: number | null };
type Session = { hash: string; csrfHash: string; deviceId: string; createdAt: number; reauthenticatedAt: number; lastSeenAt: number; idleExpiresAt: number; absoluteExpiresAt: number; revokedAt: number | null };
type Ceremony = {
  id: string;
  challengeHash: string;
  purpose: "bootstrap" | "additional" | "authentication" | "recovery";
  deviceId: string | null;
  bootstrapHash: string | null;
  recoveryHash: string | null;
  recoveryGeneration: number | null;
  authorizingSessionHash: string | null;
  label: string | null;
  expiresAt: number;
  consumed: boolean;
};

export type BootstrapWindow = Readonly<{ bootstrapCode: string; expiresAt: number }>;
export type EnrollmentCeremony = Readonly<{ ceremonyId: string; challenge: string; origin: string; rpId: string; expiresAt: number }>;
export type AuthenticationCeremony = Readonly<{ ceremonyId: string; challenge: string; origin: string; rpId: string; expiresAt: number }>;
export type SessionGrant = Readonly<{
  /** Test-only stand-in for the browser's HttpOnly cookie transport. */
  cookie: string;
  cookieHeader: string;
  csrf: string;
  device: Readonly<{ id: string; label: string; revision: number }>;
  /** Shown exactly once after bootstrap or recovery; server state retains hashes only. */
  recoveryCodes: readonly string[];
}>;
export type DeviceProjection = Readonly<{ id: string; label: string; revision: number; createdAt: number; activeSessionCount: number }>;

export type FinishEnrollmentInput = Readonly<{
  ceremonyId: string;
  challenge: string;
  origin: string;
  rpId: string;
  credentialId: string;
  userVerified: boolean;
  backupEligible: boolean;
  signatureValid: boolean;
}>;

export type FinishAuthenticationInput = Readonly<{
  ceremonyId: string;
  challenge: string;
  origin: string;
  rpId: string;
  userVerified: boolean;
  backupEligible: boolean;
  signatureValid: boolean;
  counter: number;
}>;

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("base64url");
}

function sameSecret(candidate: string, expectedHash: string): boolean {
  if (!/^[A-Za-z0-9_-]{16,128}$/u.test(candidate)) return false;
  const candidateHash = Buffer.from(sha256(candidate), "utf8");
  const storedHash = Buffer.from(expectedHash, "utf8");
  return candidateHash.length === storedHash.length && timingSafeEqual(candidateHash, storedHash);
}

function randomSecret(randomBytes: RandomBytes, bytes: number): string {
  const value = randomBytes(bytes);
  if (!(value instanceof Uint8Array) || value.byteLength !== bytes) throw new RemoteAuthPrototypeError("invalid_configuration");
  return Buffer.from(value).toString("base64url");
}

function canonicalOrigin(input: string): { origin: string; hostname: string } {
  let parsed: URL;
  try { parsed = new URL(input); } catch { throw new RemoteAuthPrototypeError("invalid_configuration"); }
  const hostname = parsed.hostname.toLowerCase();
  const dnsName = hostname.length <= 253
    && hostname.split(".").every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/u.test(label));
  if (
    input !== parsed.origin
    || parsed.protocol !== "https:"
    || !dnsName
    || parsed.port
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
  ) throw new RemoteAuthPrototypeError("invalid_configuration");
  return { origin: parsed.origin, hostname };
}

function validLabel(label: string): boolean {
  return label.length > 0 && [...label].length <= 64 && label.trim() === label && !/\p{C}/u.test(label);
}

function fixedResponse(status: PrototypeResponse["status"], body: PrototypeResponse["body"]): PrototypeResponse {
  return { status, body, headers: { "Cache-Control": "no-store" } };
}

function normalizeHeaders(headers: PrototypeRequest["headers"]): Map<string, string> | null {
  const normalized = new Map<string, string>();
  for (const [name, value] of Object.entries(headers ?? {})) {
    const key = name.toLowerCase();
    if (!/^[!#$%&'*+.^_`|~0-9a-z-]+$/u.test(key) || typeof value !== "string" || value.length > 8_192 || /[\r\n\0]/u.test(value) || normalized.has(key)) return null;
    normalized.set(key, value);
  }
  return normalized;
}

function readCookie(header: string | undefined): string | null {
  if (!header || /[\r\n\0]/u.test(header)) return null;
  let result: string | null = null;
  for (const item of header.split(";")) {
    const [name, ...parts] = item.trim().split("=");
    if (name !== SESSION_COOKIE_NAME) continue;
    if (result !== null || parts.length !== 1 || !/^[A-Za-z0-9_-]{43}$/u.test(parts[0])) return null;
    result = parts[0];
  }
  return result;
}

function exactIntentBody(body: unknown, intent: string): boolean {
  if (!body || typeof body !== "object" || Array.isArray(body)) return false;
  const record = body as Record<string, unknown>;
  return Object.keys(record).length === 1 && record.intent === intent;
}

export type RemoteAuthPrototype = Readonly<{
  openBootstrap(): BootstrapWindow;
  startBootstrapEnrollment(input: Readonly<{ bootstrapCode: string; label: string }>): EnrollmentCeremony;
  startAdditionalEnrollment(request: PrototypeRequest, label: string): EnrollmentCeremony;
  startRecoveryEnrollment(input: Readonly<{ recoveryCode: string; label: string }>): EnrollmentCeremony;
  finishEnrollment(input: FinishEnrollmentInput): SessionGrant;
  startAuthentication(input: Readonly<{ deviceId: string }>): AuthenticationCeremony;
  finishAuthentication(input: FinishAuthenticationInput): SessionGrant;
  handle(request: PrototypeRequest): PrototypeResponse;
  listDevices(cookieHeader: string): readonly DeviceProjection[];
  revokeDevice(input: Readonly<{ request: PrototypeRequest; deviceId: string; expectedDeviceRevision: number }>): void;
  signOutAll(request: PrototypeRequest): void;
  /** Safe, test-facing state; it intentionally contains no session/cookie/challenge/credential values. */
  getPrototypeState(): Readonly<{ hasBootstrapWindow: boolean; deviceCount: number; activeSessionCount: number; ceremonyCount: number; recoveryCodeCount: number }>;
}>;

export function createRemoteAuthPrototype({
  canonicalOrigin: originInput,
  now = Date.now,
  randomBytes = nodeRandomBytes,
  bridge = createInMemoryPrototypeBridge(),
}: Readonly<{ canonicalOrigin: string; now?: Clock; randomBytes?: RandomBytes; bridge?: PrototypeFakeBridge }>): RemoteAuthPrototype {
  const canonical = canonicalOrigin(originInput);
  let bootstrap: Bootstrap | null = null;
  const devices = new Map<string, Device>();
  const sessions = new Map<string, Session>();
  const ceremonies = new Map<string, Ceremony>();
  /** The map key is a SHA-256 recovery-code hash; recovery codes are never retained in plaintext. */
  const recoveryCodeHashes = new Set<string>();
  /** Pending ceremonies reserve a hash without consuming its corresponding recovery code. */
  const reservedRecoveryCodeHashes = new Set<string>();
  let recoveryGeneration = 0;

  const sessionForCookie = (cookieHeader: string, touch: boolean): Session | null => {
    const secret = readCookie(cookieHeader);
    if (!secret) return null;
    const session = sessions.get(sha256(secret));
    if (!session || !sameSecret(secret, session.hash)) return null;
    const timestamp = now();
    const device = devices.get(session.deviceId);
    if (session.revokedAt !== null || !device || device.revokedAt !== null || timestamp >= session.idleExpiresAt || timestamp >= session.absoluteExpiresAt) {
      session.revokedAt ??= timestamp;
      return null;
    }
    if (touch) {
      session.lastSeenAt = timestamp;
      session.idleExpiresAt = timestamp + SESSION_IDLE_MS;
    }
    return session;
  };

  const prepareSession = (device: Device, recoveryCodes: readonly string[] = []): Readonly<{ hash: string; session: Session; grant: SessionGrant }> => {
    const cookie = randomSecret(randomBytes, 32);
    const csrf = randomSecret(randomBytes, 32);
    const timestamp = now();
    const hash = sha256(cookie);
    const session: Session = {
      hash,
      csrfHash: sha256(csrf),
      deviceId: device.id,
      createdAt: timestamp,
      reauthenticatedAt: timestamp,
      lastSeenAt: timestamp,
      idleExpiresAt: timestamp + SESSION_IDLE_MS,
      absoluteExpiresAt: timestamp + SESSION_ABSOLUTE_MS,
      revokedAt: null,
    };
    return {
      hash,
      session,
      grant: {
      cookie: `${SESSION_COOKIE_NAME}=${cookie}; Path=/; Secure; HttpOnly; SameSite=Strict`,
      cookieHeader: `${SESSION_COOKIE_NAME}=${cookie}`,
      csrf,
      device: { id: device.id, label: device.label, revision: device.revision },
      recoveryCodes,
      },
    };
  };

  const issueSession = (device: Device, recoveryCodes: readonly string[] = []): SessionGrant => {
    const prepared = prepareSession(device, recoveryCodes);
    sessions.set(prepared.hash, prepared.session);
    return prepared.grant;
  };

  const ceremonyOutput = (ceremony: Ceremony, challenge: string): EnrollmentCeremony => ({
    ceremonyId: ceremony.id, challenge, origin: canonical.origin, rpId: canonical.hostname, expiresAt: ceremony.expiresAt,
  });

  const consumeCeremony = (id: string): Ceremony => {
    pruneCeremonies();
    const ceremony = ceremonies.get(id);
    if (!ceremony || ceremony.consumed || now() >= ceremony.expiresAt) {
      if (ceremony) ceremony.consumed = true;
      throw new RemoteAuthPrototypeError("ceremony_invalid");
    }
    ceremonies.delete(id);
    return ceremony;
  };

  const validCeremonyEvidence = (ceremony: Ceremony, input: { challenge: string; origin: string; rpId: string; userVerified: boolean; backupEligible: boolean; signatureValid: boolean }): boolean =>
    sameSecret(input.challenge, ceremony.challengeHash)
    && input.origin === canonical.origin
    && input.rpId === canonical.hostname
    && input.userVerified === true
    && input.backupEligible === false
    && input.signatureValid === true;

  const pruneCeremonies = (): void => {
    const timestamp = now();
    for (const [id, ceremony] of ceremonies) {
      if (ceremony.consumed || timestamp >= ceremony.expiresAt) {
        ceremonies.delete(id);
        if (ceremony.recoveryHash) reservedRecoveryCodeHashes.delete(ceremony.recoveryHash);
      }
    }
  };

  const reserveCeremony = (): void => {
    pruneCeremonies();
    if (ceremonies.size >= MAX_ACTIVE_CEREMONIES) throw new RemoteAuthPrototypeError("ceremony_invalid");
  };

  const generateRecoveryCodes = (): Readonly<{ plainCodes: readonly string[]; hashes: ReadonlySet<string> }> => {
    const plainCodes: string[] = [];
    const hashes = new Set<string>();
    for (let attempts = 0; hashes.size < RECOVERY_CODE_COUNT && attempts < MAX_RECOVERY_CODE_GENERATION_ATTEMPTS; attempts += 1) {
      const code = randomSecret(randomBytes, 16);
      const hash = sha256(code);
      if (hashes.has(hash)) continue;
      hashes.add(hash);
      plainCodes.push(code);
    }
    if (hashes.size !== RECOVERY_CODE_COUNT) throw new RemoteAuthPrototypeError("invalid_configuration");
    return Object.freeze({ plainCodes: Object.freeze(plainCodes), hashes });
  };

  const installRecoveryCodes = (generated: Readonly<{ plainCodes: readonly string[]; hashes: ReadonlySet<string> }>): readonly string[] => {
    recoveryCodeHashes.clear();
    for (const hash of generated.hashes) recoveryCodeHashes.add(hash);
    reservedRecoveryCodeHashes.clear();
    recoveryGeneration += 1;
    return generated.plainCodes;
  };

  const revokeAllSessions = (timestamp: number): void => {
    for (const session of sessions.values()) session.revokedAt ??= timestamp;
  };

  const requireUnsafeRequest = (request: PrototypeRequest, expectedPath: string, expectedIntent: string): Session | null => {
    const headers = normalizeHeaders(request.headers);
    if (!headers || request.method !== "POST" || request.path !== expectedPath || !exactIntentBody(request.body, expectedIntent)) return null;
    if (FORWARDED_HEADERS.size && [...FORWARDED_HEADERS].some((header) => headers.has(header))) return null;
    if (headers.get("host") !== canonical.hostname || headers.get("origin") !== canonical.origin) return null;
    const fetchSite = headers.get("sec-fetch-site");
    if (fetchSite !== undefined && fetchSite !== "same-origin") return null;
    const session = sessionForCookie(headers.get("cookie") ?? "", true);
    const csrf = headers.get("x-mentat-csrf");
    if (!session || !csrf || !sameSecret(csrf, session.csrfHash)) return null;
    return session;
  };

  return Object.freeze({
    openBootstrap(): BootstrapWindow {
      if (devices.size > 0) throw new RemoteAuthPrototypeError("bootstrap_unavailable");
      const code = randomSecret(randomBytes, 16);
      const expiresAt = now() + BOOTSTRAP_WINDOW_MS;
      bootstrap = { codeHash: sha256(code), expiresAt };
      return { bootstrapCode: code, expiresAt };
    },

    startBootstrapEnrollment(input: Readonly<{ bootstrapCode: string; label: string }>): EnrollmentCeremony {
      if (!bootstrap || now() >= bootstrap.expiresAt || !validLabel(input.label) || !sameSecret(input.bootstrapCode, bootstrap.codeHash)) {
        throw new RemoteAuthPrototypeError("bootstrap_invalid");
      }
      reserveCeremony();
      const challenge = randomSecret(randomBytes, 32);
      const ceremony: Ceremony = {
        id: `ceremony_${randomSecret(randomBytes, 16)}`,
        challengeHash: sha256(challenge),
        purpose: "bootstrap",
        deviceId: null,
        bootstrapHash: bootstrap.codeHash,
        recoveryHash: null,
        recoveryGeneration: null,
        authorizingSessionHash: null,
        label: input.label,
        expiresAt: Math.min(now() + CEREMONY_WINDOW_MS, bootstrap.expiresAt),
        consumed: false,
      };
      ceremonies.set(ceremony.id, ceremony);
      return ceremonyOutput(ceremony, challenge);
    },

    startAdditionalEnrollment(request: PrototypeRequest, label: string): EnrollmentCeremony {
      const session = requireUnsafeRequest(request, "/prototype/security/add-device", "add_device");
      if (!session || !validLabel(label) || now() - session.reauthenticatedAt > REAUTH_WINDOW_MS) throw new RemoteAuthPrototypeError("session_invalid");
      reserveCeremony();
      const challenge = randomSecret(randomBytes, 32);
      const ceremony: Ceremony = {
        id: `ceremony_${randomSecret(randomBytes, 16)}`,
        challengeHash: sha256(challenge),
        purpose: "additional",
        deviceId: null,
        bootstrapHash: null,
        recoveryHash: null,
        recoveryGeneration: null,
        authorizingSessionHash: session.hash,
        label,
        expiresAt: now() + CEREMONY_WINDOW_MS,
        consumed: false,
      };
      ceremonies.set(ceremony.id, ceremony);
      return ceremonyOutput(ceremony, challenge);
    },

    startRecoveryEnrollment(input: Readonly<{ recoveryCode: string; label: string }>): EnrollmentCeremony {
      if (!validLabel(input.label) || !/^[A-Za-z0-9_-]{16,128}$/u.test(input.recoveryCode)) throw new RemoteAuthPrototypeError("ceremony_invalid");
      reserveCeremony();
      const recoveryHash = sha256(input.recoveryCode);
      if (!recoveryCodeHashes.has(recoveryHash) || reservedRecoveryCodeHashes.has(recoveryHash)) throw new RemoteAuthPrototypeError("ceremony_invalid");
      const challenge = randomSecret(randomBytes, 32);
      const ceremony: Ceremony = {
        id: `ceremony_${randomSecret(randomBytes, 16)}`,
        challengeHash: sha256(challenge),
        purpose: "recovery",
        deviceId: null,
        bootstrapHash: null,
        recoveryHash,
        recoveryGeneration,
        authorizingSessionHash: null,
        label: input.label,
        expiresAt: now() + CEREMONY_WINDOW_MS,
        consumed: false,
      };
      reservedRecoveryCodeHashes.add(recoveryHash);
      ceremonies.set(ceremony.id, ceremony);
      return ceremonyOutput(ceremony, challenge);
    },

    finishEnrollment(input: FinishEnrollmentInput): SessionGrant {
      if (!CEREMONY_ID.test(input.ceremonyId)) throw new RemoteAuthPrototypeError("ceremony_invalid");
      const ceremony = consumeCeremony(input.ceremonyId);
      try {
        if (!CREDENTIAL_ID.test(input.credentialId) || (ceremony.purpose !== "bootstrap" && ceremony.purpose !== "additional" && ceremony.purpose !== "recovery") || !validCeremonyEvidence(ceremony, input)) throw new RemoteAuthPrototypeError("ceremony_invalid");
        if (ceremony.purpose === "bootstrap" && (!bootstrap || now() >= bootstrap.expiresAt || ceremony.bootstrapHash !== bootstrap.codeHash || devices.size !== 0)) throw new RemoteAuthPrototypeError("bootstrap_invalid");
        if (ceremony.purpose === "additional") {
          const authorizingSession = ceremony.authorizingSessionHash ? sessions.get(ceremony.authorizingSessionHash) : null;
          const authorizingDevice = authorizingSession ? devices.get(authorizingSession.deviceId) : null;
          if (!authorizingSession || !authorizingDevice || authorizingSession.revokedAt !== null || authorizingDevice.revokedAt !== null || now() >= authorizingSession.idleExpiresAt || now() >= authorizingSession.absoluteExpiresAt || now() - authorizingSession.reauthenticatedAt > REAUTH_WINDOW_MS) throw new RemoteAuthPrototypeError("session_invalid");
        }
        if (ceremony.purpose === "recovery" && (!ceremony.recoveryHash || ceremony.recoveryGeneration !== recoveryGeneration || !reservedRecoveryCodeHashes.has(ceremony.recoveryHash) || !recoveryCodeHashes.has(ceremony.recoveryHash))) throw new RemoteAuthPrototypeError("ceremony_invalid");
        const credentialHash = sha256(input.credentialId);
        if ([...devices.values()].some((device) => device.credentialHash === credentialHash)) throw new RemoteAuthPrototypeError("ceremony_invalid");
        const recoveryReplacement = ceremony.purpose === "bootstrap" || ceremony.purpose === "recovery" ? generateRecoveryCodes() : null;
        const timestamp = now();
        const device: Device = { id: `device_${randomSecret(randomBytes, 16)}`, credentialHash, label: ceremony.label ?? "", revision: 1, createdAt: timestamp, lastCounter: 0, revokedAt: null };
        const recoveryCodes = recoveryReplacement?.plainCodes ?? [];
        const preparedSession = prepareSession(device, recoveryCodes);
        devices.set(device.id, device);
        if (ceremony.purpose === "bootstrap") bootstrap = null;
        if (ceremony.purpose === "additional" || ceremony.purpose === "recovery") revokeAllSessions(timestamp);
        if (ceremony.purpose === "recovery") {
          for (const existing of devices.values()) {
            if (existing.id !== device.id) {
              existing.revokedAt = timestamp;
              existing.revision += 1;
            }
          }
        }
        if (recoveryReplacement) installRecoveryCodes(recoveryReplacement);
        sessions.set(preparedSession.hash, preparedSession.session);
        return preparedSession.grant;
      } finally {
        if (ceremony.recoveryHash) reservedRecoveryCodeHashes.delete(ceremony.recoveryHash);
      }
    },

    startAuthentication(input: Readonly<{ deviceId: string }>): AuthenticationCeremony {
      const device = devices.get(input.deviceId);
      if (!DEVICE_ID.test(input.deviceId) || !device || device.revokedAt !== null) throw new RemoteAuthPrototypeError("ceremony_invalid");
      reserveCeremony();
      const challenge = randomSecret(randomBytes, 32);
      const ceremony: Ceremony = {
        id: `ceremony_${randomSecret(randomBytes, 16)}`,
        challengeHash: sha256(challenge),
        purpose: "authentication",
        deviceId: device.id,
        bootstrapHash: null,
        recoveryHash: null,
        recoveryGeneration: null,
        authorizingSessionHash: null,
        label: null,
        expiresAt: now() + CEREMONY_WINDOW_MS,
        consumed: false,
      };
      ceremonies.set(ceremony.id, ceremony);
      return ceremonyOutput(ceremony, challenge);
    },

    finishAuthentication(input: FinishAuthenticationInput): SessionGrant {
      if (!CEREMONY_ID.test(input.ceremonyId)) throw new RemoteAuthPrototypeError("ceremony_invalid");
      const ceremony = consumeCeremony(input.ceremonyId);
      const device = ceremony.deviceId ? devices.get(ceremony.deviceId) : null;
      if (!Number.isSafeInteger(input.counter) || input.counter < 1 || ceremony.purpose !== "authentication" || !device || device.revokedAt !== null || input.counter <= device.lastCounter || !validCeremonyEvidence(ceremony, input)) throw new RemoteAuthPrototypeError("ceremony_invalid");
      device.lastCounter = input.counter;
      return issueSession(device);
    },

    handle(request: PrototypeRequest): PrototypeResponse {
      const headers = normalizeHeaders(request.headers);
      if (!headers) return fixedResponse(400, { status: "invalid" });
      if ([...FORWARDED_HEADERS].some((header) => headers.has(header)) || headers.has("x-mentat-bridge-target") || headers.has("x-bridge-target")) return fixedResponse(400, { status: "invalid" });
      if (headers.get("host") !== canonical.hostname || headers.get("origin") !== canonical.origin) return fixedResponse(403, { status: "forbidden" });
      const fetchSite = headers.get("sec-fetch-site");
      if (fetchSite !== undefined && fetchSite !== "same-origin") return fixedResponse(403, { status: "forbidden" });
      if (request.path.includes("?") || request.path.includes("#")) return fixedResponse(404, { status: "not_found" });
      if (request.path === "/prototype/fake-read") {
        if (request.method !== "GET") return fixedResponse(405, { status: "method_not_allowed" });
        if (request.body !== undefined) return fixedResponse(400, { status: "invalid" });
        if (!sessionForCookie(headers.get("cookie") ?? "", true)) return fixedResponse(401, { status: "unauthenticated" });
        bridge.call("prototype.fixed_read");
        return fixedResponse(200, { status: "ok" });
      }
      if (request.path === "/prototype/fake-mutate") {
        if (request.method !== "POST") return fixedResponse(405, { status: "method_not_allowed" });
        if (!exactIntentBody(request.body, "fake_mutation")) return fixedResponse(400, { status: "invalid" });
        const session = sessionForCookie(headers.get("cookie") ?? "", true);
        const csrf = headers.get("x-mentat-csrf");
        if (!session || !csrf || !sameSecret(csrf, session.csrfHash)) return fixedResponse(401, { status: "unauthenticated" });
        bridge.call("prototype.fixed_mutation");
        return fixedResponse(200, { status: "ok" });
      }
      return fixedResponse(404, { status: "not_found" });
    },

    listDevices(cookieHeader: string): readonly DeviceProjection[] {
      if (!sessionForCookie(cookieHeader, true)) throw new RemoteAuthPrototypeError("session_invalid");
      return [...devices.values()]
        .filter((device) => device.revokedAt === null)
        .map((device) => ({ id: device.id, label: device.label, revision: device.revision, createdAt: device.createdAt, activeSessionCount: [...sessions.values()].filter((session) => session.deviceId === device.id && session.revokedAt === null && now() < session.idleExpiresAt && now() < session.absoluteExpiresAt).length }));
    },

    revokeDevice(input: Readonly<{ request: PrototypeRequest; deviceId: string; expectedDeviceRevision: number }>): void {
      if (!requireUnsafeRequest(input.request, "/prototype/security/revoke-device", "revoke_device") || !DEVICE_ID.test(input.deviceId) || !Number.isSafeInteger(input.expectedDeviceRevision)) throw new RemoteAuthPrototypeError("session_invalid");
      const device = devices.get(input.deviceId);
      if (!device || device.revokedAt !== null || device.revision !== input.expectedDeviceRevision) throw new RemoteAuthPrototypeError("ceremony_invalid");
      if ([...devices.values()].filter((candidate) => candidate.revokedAt === null).length <= 1) throw new RemoteAuthPrototypeError("last_device");
      const timestamp = now();
      device.revokedAt = timestamp;
      device.revision += 1;
      for (const session of sessions.values()) if (session.deviceId === device.id) session.revokedAt = timestamp;
    },

    signOutAll(request: PrototypeRequest): void {
      const session = requireUnsafeRequest(request, "/prototype/security/sign-out-all", "sign_out_all");
      if (!session) throw new RemoteAuthPrototypeError("session_invalid");
      const timestamp = now();
      revokeAllSessions(timestamp);
    },

    getPrototypeState(): Readonly<{ hasBootstrapWindow: boolean; deviceCount: number; activeSessionCount: number; ceremonyCount: number; recoveryCodeCount: number }> {
      pruneCeremonies();
      const timestamp = now();
      return {
        hasBootstrapWindow: bootstrap !== null && timestamp < bootstrap.expiresAt,
        deviceCount: [...devices.values()].filter((device) => device.revokedAt === null).length,
        activeSessionCount: [...sessions.values()].filter((session) => session.revokedAt === null && timestamp < session.idleExpiresAt && timestamp < session.absoluteExpiresAt).length,
        ceremonyCount: [...ceremonies.values()].filter((ceremony) => !ceremony.consumed && timestamp < ceremony.expiresAt).length,
        recoveryCodeCount: recoveryCodeHashes.size,
      };
    },
  });
}

/**
 * Fixture text for MDA-1 tests and review. It is intentionally not written to
 * Caddy's configuration directory and is not consumed by any launcher.
 */
export function renderPrototypeCaddyfile({ canonicalOrigin: originInput, nodePort }: Readonly<{ canonicalOrigin: string; nodePort: number }>): string {
  const canonical = canonicalOrigin(originInput);
  if (!Number.isSafeInteger(nodePort) || nodePort < 1 || nodePort > 65_535) throw new RemoteAuthPrototypeError("invalid_configuration");
  return `# MDA-1 disposable fixture only: never installed by Mentat.
${canonical.origin} {
  reverse_proxy 127.0.0.1:${nodePort} {
    header_up -Forwarded
    header_up -X-Forwarded-For
    header_up -X-Forwarded-Host
    header_up -X-Forwarded-Proto
    header_up -X-Real-IP
  }
}`;
}
