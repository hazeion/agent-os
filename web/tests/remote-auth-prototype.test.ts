import assert from "node:assert/strict";
import test from "node:test";

import {
  createInMemoryPrototypeBridge,
  createRemoteAuthPrototype,
  RemoteAuthPrototypeError,
  renderPrototypeCaddyfile,
  type RemoteAuthPrototype,
  type SessionGrant,
} from "../src/lib/remote-auth-prototype.ts";

const canonicalOrigin = "https://mentat.example.test";
const canonicalHost = "mentat.example.test";
const initialTime = 1_700_000_000_000;

function fixture(): {
  auth: RemoteAuthPrototype;
  bridge: ReturnType<typeof createInMemoryPrototypeBridge>;
  setNow(value: number): void;
} {
  let timestamp = initialTime;
  const bridge = createInMemoryPrototypeBridge();
  return {
    auth: createRemoteAuthPrototype({ canonicalOrigin, bridge, now: () => timestamp }),
    bridge,
    setNow(value: number): void { timestamp = value; },
  };
}

function assertPrototypeError(action: () => unknown, code: RemoteAuthPrototypeError["code"]): void {
  assert.throws(action, (error: unknown) => error instanceof RemoteAuthPrototypeError && error.code === code);
}

function protectedHeaders(grant: SessionGrant, extra: Record<string, string> = {}): Record<string, string> {
  return {
    cookie: grant.cookieHeader,
    host: canonicalHost,
    origin: canonicalOrigin,
    "sec-fetch-site": "same-origin",
    "x-mentat-csrf": grant.csrf,
    ...extra,
  };
}

function enrollFirstDevice(auth: RemoteAuthPrototype, label = "Primary passkey"): SessionGrant {
  const bootstrap = auth.openBootstrap();
  const ceremony = auth.startBootstrapEnrollment({ bootstrapCode: bootstrap.bootstrapCode, label });
  return auth.finishEnrollment({
    backupEligible: false,
    ceremonyId: ceremony.ceremonyId,
    challenge: ceremony.challenge,
    credentialId: `credential_${"a".repeat(24)}`,
    origin: ceremony.origin,
    rpId: ceremony.rpId,
    signatureValid: true,
    userVerified: true,
  });
}

function authenticate(auth: RemoteAuthPrototype, deviceId: string, counter: number): SessionGrant {
  const ceremony = auth.startAuthentication({ deviceId });
  return auth.finishAuthentication({
    backupEligible: false,
    ceremonyId: ceremony.ceremonyId,
    challenge: ceremony.challenge,
    counter,
    origin: ceremony.origin,
    rpId: ceremony.rpId,
    signatureValid: true,
    userVerified: true,
  });
}

test("remote auth prototype fixes the canonical edge and rejects forged proxy or bridge routing before the fake bridge", () => {
  const { auth, bridge } = fixture();
  const grant = enrollFirstDevice(auth);
  const base = { headers: protectedHeaders(grant), method: "GET", path: "/prototype/fake-read" } as const;

  for (const [name, request, status] of [
    ["forged host", { ...base, headers: protectedHeaders(grant, { host: "evil.example" }) }, 403],
    ["forged Origin", { ...base, headers: protectedHeaders(grant, { origin: "https://evil.example" }) }, 403],
    ["Forwarded", { ...base, headers: protectedHeaders(grant, { forwarded: "host=evil.example;proto=https" }) }, 400],
    ["X-Forwarded-Host", { ...base, headers: protectedHeaders(grant, { "x-forwarded-host": "evil.example" }) }, 400],
    ["browser bridge header", { ...base, headers: protectedHeaders(grant, { "x-mentat-bridge-target": "http://127.0.0.1:9999" }) }, 400],
    ["browser bridge body", { ...base, body: { bridgeTarget: "python-private-bridge" } }, 400],
    ["browser bridge query", { ...base, path: "/prototype/fake-read?bridgeTarget=python-private-bridge" }, 404],
  ] as const) {
    const response = auth.handle(request);
    assert.equal(response.status, status, name);
    assert.equal(response.headers["Cache-Control"], "no-store", name);
    assert.deepEqual(bridge.calls(), [], name);
  }

  const caddyfile = renderPrototypeCaddyfile({ canonicalOrigin, nodePort: 8888 });
  assert.match(caddyfile, /^https:\/\/mentat\.example\.test \{/m);
  assert.match(caddyfile, /reverse_proxy 127\.0\.0\.1:8888/);
  for (const header of ["Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP"]) {
    assert.match(caddyfile, new RegExp(`header_up -${header}`));
  }
  assert.doesNotMatch(caddyfile, /python|bridge token|sqlite|adapter/i);
});

test("remote auth prototype consumes invalid ceremonies and rejects replayed or expired WebAuthn evidence", () => {
  const first = fixture();
  const bootstrap = first.auth.openBootstrap();
  const ceremony = first.auth.startBootstrapEnrollment({ bootstrapCode: bootstrap.bootstrapCode, label: "Primary passkey" });
  const enrollment = {
    backupEligible: false,
    ceremonyId: ceremony.ceremonyId,
    challenge: ceremony.challenge,
    credentialId: `credential_${"b".repeat(24)}`,
    origin: ceremony.origin,
    rpId: ceremony.rpId,
    signatureValid: true,
    userVerified: true,
  };

  assertPrototypeError(() => first.auth.finishEnrollment({ ...enrollment, signatureValid: false }), "ceremony_invalid");
  assertPrototypeError(() => first.auth.finishEnrollment({ ...enrollment, origin: "https://evil.example" }), "ceremony_invalid");
  assertPrototypeError(() => first.auth.finishEnrollment(enrollment), "ceremony_invalid");
  assert.equal(first.auth.getPrototypeState().deviceCount, 0);
  assert.equal(first.auth.getPrototypeState().ceremonyCount, 0);

  const expired = fixture();
  const expiredBootstrap = expired.auth.openBootstrap();
  const expiredCeremony = expired.auth.startBootstrapEnrollment({ bootstrapCode: expiredBootstrap.bootstrapCode, label: "Expired passkey" });
  expired.setNow(expiredCeremony.expiresAt);
  assertPrototypeError(() => expired.auth.finishEnrollment({
    backupEligible: false,
    ceremonyId: expiredCeremony.ceremonyId,
    challenge: expiredCeremony.challenge,
    credentialId: `credential_${"c".repeat(24)}`,
    origin: expiredCeremony.origin,
    rpId: expiredCeremony.rpId,
    signatureValid: true,
    userVerified: true,
  }), "ceremony_invalid");
  assert.equal(expired.auth.getPrototypeState().deviceCount, 0);

  const used = fixture();
  const grant = enrollFirstDevice(used.auth);
  assertPrototypeError(() => used.auth.startBootstrapEnrollment({ bootstrapCode: "not-a-reusable-bootstrap-code", label: "Second passkey" }), "bootstrap_invalid");
  assert.equal(used.auth.getPrototypeState().deviceCount, 1);
  assert.match(grant.cookie, /^__Host-mentat-prototype=[A-Za-z0-9_-]{43}; Path=\/; Secure; HttpOnly; SameSite=Strict$/);
});

test("remote auth prototype produces distinct opaque sessions and invalidates every session on sign-out-all", () => {
  const { auth, bridge } = fixture();
  const first = enrollFirstDevice(auth);
  const second = authenticate(auth, first.device.id, 1);

  assert.notEqual(first.cookieHeader, second.cookieHeader, "login must not reuse a session cookie");
  assert.notEqual(first.csrf, second.csrf, "login must rotate the session-bound CSRF secret");
  assert.equal(auth.getPrototypeState().activeSessionCount, 2);
  assert.doesNotMatch(JSON.stringify(auth.getPrototypeState()), /__Host-|credential_|csrf/i);

  assert.equal(auth.handle({ headers: protectedHeaders(first), method: "GET", path: "/prototype/fake-read" }).status, 200);
  assert.equal(auth.handle({ headers: protectedHeaders(second), method: "GET", path: "/prototype/fake-read" }).status, 200);
  assert.deepEqual(bridge.calls(), ["prototype.fixed_read", "prototype.fixed_read"]);

  auth.signOutAll({ body: { intent: "sign_out_all" }, headers: protectedHeaders(second), method: "POST", path: "/prototype/security/sign-out-all" });
  assert.equal(auth.getPrototypeState().activeSessionCount, 0);
  for (const grant of [first, second]) {
    const response = auth.handle({ headers: protectedHeaders(grant), method: "GET", path: "/prototype/fake-read" });
    assert.equal(response.status, 401);
  }
  assert.deepEqual(bridge.calls(), ["prototype.fixed_read", "prototype.fixed_read"], "revoked sessions never reach the bridge");
});

test("remote auth prototype expires an absolute session window before any fake bridge call", () => {
  const { auth, bridge, setNow } = fixture();
  const grant = enrollFirstDevice(auth);
  setNow(initialTime + (24 * 60 * 60 * 1_000));

  const response = auth.handle({ headers: protectedHeaders(grant), method: "GET", path: "/prototype/fake-read" });
  assert.equal(response.status, 401);
  assert.equal(auth.getPrototypeState().activeSessionCount, 0);
  assert.deepEqual(bridge.calls(), []);
});

test("remote auth prototype revokes a device and each of its sessions with exact CSRF-bound security calls", () => {
  const { auth, bridge } = fixture();
  const owner = enrollFirstDevice(auth);
  const addCeremony = auth.startAdditionalEnrollment(
    { body: { intent: "add_device" }, headers: protectedHeaders(owner), method: "POST", path: "/prototype/security/add-device" },
    "Laptop passkey",
  );
  const deviceGrant = auth.finishEnrollment({
    backupEligible: false,
    ceremonyId: addCeremony.ceremonyId,
    challenge: addCeremony.challenge,
    credentialId: `credential_${"d".repeat(24)}`,
    origin: addCeremony.origin,
    rpId: addCeremony.rpId,
    signatureValid: true,
    userVerified: true,
  });
  const deviceLogin = authenticate(auth, deviceGrant.device.id, 1);

  assertPrototypeError(() => auth.revokeDevice({
    deviceId: deviceGrant.device.id,
    expectedDeviceRevision: deviceGrant.device.revision,
    request: { body: { intent: "revoke_device" }, headers: protectedHeaders(deviceGrant, { "x-mentat-csrf": "bad" }), method: "POST", path: "/prototype/security/revoke-device" },
  }), "session_invalid");
  assert.equal(auth.getPrototypeState().activeSessionCount, 2);

  auth.revokeDevice({
    deviceId: deviceGrant.device.id,
    expectedDeviceRevision: deviceGrant.device.revision,
    request: { body: { intent: "revoke_device" }, headers: protectedHeaders(deviceGrant), method: "POST", path: "/prototype/security/revoke-device" },
  });
  assert.equal(auth.getPrototypeState().deviceCount, 1);
  for (const grant of [deviceGrant, deviceLogin]) {
    assert.equal(auth.handle({ headers: protectedHeaders(grant), method: "GET", path: "/prototype/fake-read" }).status, 401);
  }
  assert.equal(auth.handle({ headers: protectedHeaders(owner), method: "GET", path: "/prototype/fake-read" }).status, 401, "adding a device revokes the authorizing session");
  assert.deepEqual(bridge.calls(), [], "revoked-device and stale authorizing sessions cannot call the fake bridge");
});

test("remote auth prototype bounds, exactly shapes, and rechecks device-enrollment security requests", () => {
  const { auth, setNow } = fixture();
  const owner = enrollFirstDevice(auth);

  for (const body of [undefined, { intent: "add_device", extra: true }, { intent: "revoke_device" }]) {
    assertPrototypeError(() => auth.startAdditionalEnrollment(
      { body, headers: protectedHeaders(owner), method: "POST", path: "/prototype/security/add-device" },
      "Laptop passkey",
    ), "session_invalid");
  }

  for (const body of [undefined, { intent: "sign_out_all", extra: true }, { intent: "revoke_device" }]) {
    assertPrototypeError(() => auth.signOutAll({ body, headers: protectedHeaders(owner), method: "POST", path: "/prototype/security/sign-out-all" }), "session_invalid");
  }
  for (const body of [undefined, { intent: "revoke_device", extra: true }, { intent: "sign_out_all" }]) {
    assertPrototypeError(() => auth.revokeDevice({
      deviceId: owner.device.id,
      expectedDeviceRevision: owner.device.revision,
      request: { body, headers: protectedHeaders(owner), method: "POST", path: "/prototype/security/revoke-device" },
    }), "session_invalid");
  }

  setNow(initialTime + (10 * 60 * 1_000) - 1);
  const enrollment = auth.startAdditionalEnrollment(
    { body: { intent: "add_device" }, headers: protectedHeaders(owner), method: "POST", path: "/prototype/security/add-device" },
    "Laptop passkey",
  );
  setNow(initialTime + (10 * 60 * 1_000) + 1);
  assertPrototypeError(() => auth.finishEnrollment({
    backupEligible: false,
    ceremonyId: enrollment.ceremonyId,
    challenge: enrollment.challenge,
    credentialId: `credential_${"e".repeat(24)}`,
    origin: enrollment.origin,
    rpId: enrollment.rpId,
    signatureValid: true,
    userVerified: true,
  }), "session_invalid");

});

test("remote auth prototype issues ten one-use hash-only recovery codes and recovery rotates all authority", () => {
  const { auth, setNow } = fixture();
  const first = enrollFirstDevice(auth);
  assert.equal(first.recoveryCodes.length, 10);
  assert.equal(new Set(first.recoveryCodes).size, 10);
  assert.equal(auth.getPrototypeState().recoveryCodeCount, 10);
  assert.doesNotMatch(JSON.stringify(auth.getPrototypeState()), new RegExp(first.recoveryCodes[0]!));

  const invalidRecovery = auth.startRecoveryEnrollment({ label: "Recovery passkey", recoveryCode: first.recoveryCodes[0]! });
  assert.equal(auth.getPrototypeState().recoveryCodeCount, 10, "a pending ceremony only reserves the hash");
  assertPrototypeError(() => auth.finishEnrollment({
    backupEligible: false,
    ceremonyId: invalidRecovery.ceremonyId,
    challenge: invalidRecovery.challenge,
    credentialId: `credential_${"f".repeat(24)}`,
    origin: invalidRecovery.origin,
    rpId: invalidRecovery.rpId,
    signatureValid: false,
    userVerified: true,
  }), "ceremony_invalid");
  assert.equal(auth.getPrototypeState().recoveryCodeCount, 10, "invalid proof releases but does not consume the recovery code");

  const expiredRecovery = auth.startRecoveryEnrollment({ label: "Expired recovery passkey", recoveryCode: first.recoveryCodes[0]! });
  setNow(expiredRecovery.expiresAt);
  assert.equal(auth.getPrototypeState().recoveryCodeCount, 10, "expired ceremonies also release the recovery-code reservation");

  const recovery = auth.startRecoveryEnrollment({ label: "Recovery passkey", recoveryCode: first.recoveryCodes[0]! });
  const restored = auth.finishEnrollment({
    backupEligible: false,
    ceremonyId: recovery.ceremonyId,
    challenge: recovery.challenge,
    credentialId: `credential_${"f".repeat(24)}`,
    origin: recovery.origin,
    rpId: recovery.rpId,
    signatureValid: true,
    userVerified: true,
  });

  assert.equal(restored.recoveryCodes.length, 10);
  assert.equal(new Set(restored.recoveryCodes).size, 10);
  assert.equal(auth.getPrototypeState().deviceCount, 1);
  assert.equal(auth.getPrototypeState().activeSessionCount, 1);
  assert.equal(auth.getPrototypeState().recoveryCodeCount, 10, "successful recovery atomically consumes and replaces the full code set");
  assert.equal(auth.handle({ headers: protectedHeaders(first), method: "GET", path: "/prototype/fake-read" }).status, 401);
  assertPrototypeError(() => auth.startRecoveryEnrollment({ label: "Stale code", recoveryCode: first.recoveryCodes[1]! }), "ceremony_invalid");
  assert.doesNotMatch(JSON.stringify(auth.getPrototypeState()), /credential_|__Host-|csrf/i);
});

test("remote auth prototype caps pending ceremonies and discards expired ceremonies before admitting another", () => {
  const { auth, setNow } = fixture();
  const grant = enrollFirstDevice(auth);
  for (let counter = 1; counter <= 8; counter += 1) auth.startAuthentication({ deviceId: grant.device.id });
  assert.equal(auth.getPrototypeState().ceremonyCount, 8);
  assertPrototypeError(() => auth.startAuthentication({ deviceId: grant.device.id }), "ceremony_invalid");

  setNow(initialTime + (5 * 60 * 1_000));
  assert.equal(auth.startAuthentication({ deviceId: grant.device.id }).ceremonyId.startsWith("ceremony_"), true);
  assert.equal(auth.getPrototypeState().ceremonyCount, 1);
});

test("remote auth prototype rejects CSRF and method failures without calling the fake bridge", () => {
  const { auth, bridge } = fixture();
  const grant = enrollFirstDevice(auth);
  const request = { body: { intent: "fake_mutation" }, method: "POST", path: "/prototype/fake-mutate" } as const;
  const missingCsrf = protectedHeaders(grant);
  delete missingCsrf["x-mentat-csrf"];

  for (const [name, headers, status] of [
    ["missing CSRF", missingCsrf, 401],
    ["wrong CSRF", protectedHeaders(grant, { "x-mentat-csrf": "wrong" }), 401],
    ["cross-origin", protectedHeaders(grant, { origin: "https://evil.example" }), 403],
    ["cross-site metadata", protectedHeaders(grant, { "sec-fetch-site": "cross-site" }), 403],
    ["forged forwarded metadata", protectedHeaders(grant, { "x-forwarded-proto": "https" }), 400],
  ] as const) {
    const response = auth.handle({ ...request, headers });
    assert.equal(response.status, status, name);
    assert.deepEqual(bridge.calls(), [], name);
  }
  const methodFailure = auth.handle({ ...request, headers: protectedHeaders(grant), method: "GET" });
  assert.equal(methodFailure.status, 405);
  assert.deepEqual(bridge.calls(), []);

  const accepted = auth.handle({ ...request, headers: protectedHeaders(grant) });
  assert.equal(accepted.status, 200);
  assert.deepEqual(bridge.calls(), ["prototype.fixed_mutation"], "only the fixed valid route reaches the fake bridge");
});
