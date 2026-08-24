# Security policy

LeKiwi can move physical hardware. A security defect may therefore create both information-security and physical-safety risk.

## Supported versions

Security fixes target the latest `main` branch. This research-oriented fork does not promise backports.

## Report privately

Do **not** open a public issue for suspected vulnerabilities, exposed credentials, authentication bypasses, or remotely reachable unsafe motion.

Use this repository's private [GitHub Security Advisory form](https://github.com/raunaqbn/lekiwi-lerobot/security/advisories/new). Include the affected commit, component, prerequisites, reproducible proof of concept, realistic impact, and suggested fix if known. Avoid moving a real robot during testing; simulated or lifted-wheel reproduction is strongly preferred.

## Robot-control threat model

The trusted boundary is the local operator machine, Raspberry Pi, serial controllers, and private network joining them. The following are security requirements:

- Serial and camera devices have one owning process. HTTP/SSE request handlers only read cached state.
- The diagnostics and control API is not internet-safe by itself. `X-LeKiwi-Control` identifies protocol intent; it is not a credential.
- Remote access must add authenticated TLS at a reverse proxy, Cloudflare Access, or a private VPN.
- Cloudflare/Vercel static deployments contain docs and assets only; serverless code must never be presented as a real-time motor safety boundary.
- Cloudflare Access tokens are stored in the iOS Keychain and are never embedded in source, static HTML, query strings, or logs.
- Control input expires, but software timeouts are not an emergency stop. A nearby operator must retain a physical power cutoff.
- Untrusted model, dataset, calibration, URDF, and mesh files should be reviewed before loading. Pin remote revisions and prefer `safetensors` for weights.

## In scope

- Unauthorized remote control or bypass of an advertised authentication/safety boundary.
- Cross-process serial ownership failures that can cause unintended commands.
- Credential or private telemetry exposure.
- Command injection, arbitrary code execution, path traversal, unsafe deserialization, or supply-chain compromise in packaged code.
- A reproducible defect that converts stale/missing telemetry into an unsafe control decision.

## Out of scope

- Expected behavior after the user deliberately exposes the unauthenticated Flask service to the public internet.
- Damage caused by ignoring the lifted-wheel, physical-cutoff, voltage, or wiring guidance.
- Model behavior, policy quality, or an untrusted artifact the operator explicitly chose to execute.
- Scanner-only reports without a reproducible chain and concrete impact.
- Denial of service on the reporter's own local process without crossing a trust boundary.

## Safe harbor

Good-faith research that stays on equipment and accounts you own, avoids privacy violations and physical danger, and allows a reasonable remediation window is welcome. There is no monetary bounty; valid reports can be credited in the advisory if desired.
