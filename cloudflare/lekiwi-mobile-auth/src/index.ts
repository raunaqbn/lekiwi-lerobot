import { createRemoteJWKSet, jwtVerify } from "jose";

export interface Env {
  TEAM_DOMAIN: string;
  POLICY_AUD: string;
  CALLBACK_SCHEME: string;
}

type TokenVerifier = (token: string, env: Env) => Promise<void>;

const STATE_PATTERN = /^[A-Za-z0-9]{16,128}$/;
const SCHEME_PATTERN = /^[a-z][a-z0-9+.-]{2,80}$/;
const MAX_TOKEN_LENGTH = 8192;
const jwksByTeam = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

function normalizedTeamDomain(value: string): string {
  return value.replace(/\/$/, "");
}

function callbackBase(env: Env): string {
  const scheme = env.CALLBACK_SCHEME.trim().toLowerCase();
  if (!SCHEME_PATTERN.test(scheme)) {
    throw new Error("Invalid CALLBACK_SCHEME");
  }
  return `${scheme}://access/callback`;
}

export function validState(state: string | null): state is string {
  return state !== null && STATE_PATTERN.test(state);
}

export function buildCallback(token: string, state: string, env: Env): string {
  const fragment = new URLSearchParams({ token, state });
  return `${callbackBase(env)}#${fragment.toString()}`;
}

async function verifyAccessToken(token: string, env: Env): Promise<void> {
  const issuer = normalizedTeamDomain(env.TEAM_DOMAIN);
  let jwks = jwksByTeam.get(issuer);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`));
    jwksByTeam.set(issuer, jwks);
  }
  await jwtVerify(token, jwks, {
    algorithms: ["RS256"],
    audience: env.POLICY_AUD,
    issuer,
  });
}

function response(status: number, message: string): Response {
  return new Response(message, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export async function handleRequest(
  request: Request,
  env: Env,
  verifier: TokenVerifier = verifyAccessToken,
): Promise<Response> {
  const url = new URL(request.url);
  if (request.method !== "GET") return response(405, "Method not allowed");
  if (url.pathname !== "/api/mobile/auth") return response(404, "Not found");

  const state = url.searchParams.get("state");
  if (!validState(state)) return response(400, "Invalid mobile authentication state");

  const token = request.headers.get("Cf-Access-Jwt-Assertion")?.trim() ?? "";
  if (!token || token.length > MAX_TOKEN_LENGTH || token.split(".").length !== 3) {
    return response(401, "Cloudflare Access session is missing");
  }

  try {
    await verifier(token, env);
    return new Response(null, {
      status: 302,
      headers: {
        "Cache-Control": "no-store",
        Location: buildCallback(token, state, env),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return response(401, "Cloudflare Access session or callback configuration is invalid");
  }
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },
} satisfies ExportedHandler<Env>;
