import { describe, expect, it, vi } from "vitest";

import { buildCallback, handleRequest, validState, type Env } from "../src/index";

const env: Env = {
  TEAM_DOMAIN: "https://example.cloudflareaccess.com",
  POLICY_AUD: "test-audience",
  CALLBACK_SCHEME: "io.lekiwi.controller",
};
const state = "0123456789abcdef0123456789abcdef";
const token = "header.payload.signature";

describe("mobile authentication Worker", () => {
  it("accepts only a bounded alphanumeric state", () => {
    expect(validState(state)).toBe(true);
    expect(validState("too-short")).toBe(false);
    expect(validState(`${state}_`)).toBe(false);
  });

  it("returns a verified token through the configured callback", async () => {
    const verifier = vi.fn().mockResolvedValue(undefined);
    const response = await handleRequest(
      new Request(`https://robot.example.com/api/mobile/auth?state=${state}`, {
        headers: { "Cf-Access-Jwt-Assertion": token },
      }),
      env,
      verifier,
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toBe(buildCallback(token, state, env));
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("rejects unverified or missing tokens and non-exact routes", async () => {
    const invalid = await handleRequest(
      new Request(`https://robot.example.com/api/mobile/auth?state=${state}`, {
        headers: { "Cf-Access-Jwt-Assertion": token },
      }),
      env,
      vi.fn().mockRejectedValue(new Error("bad signature")),
    );
    const missing = await handleRequest(
      new Request(`https://robot.example.com/api/mobile/auth?state=${state}`),
      env,
    );
    const other = await handleRequest(
      new Request(`https://robot.example.com/api/mobile/auth/extra?state=${state}`),
      env,
    );
    expect(invalid.status).toBe(401);
    expect(missing.status).toBe(401);
    expect(other.status).toBe(404);
  });
});
