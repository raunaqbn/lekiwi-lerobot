# LeKiwi mobile authentication Worker

This optional Worker handles only `/api/mobile/auth`. Cloudflare Access authenticates the operator first; the Worker verifies the signed Access application JWT and returns it through a state-bound custom URL callback to the iOS app.

The dashboard, camera streams, telemetry, and control routes continue through Cloudflare Tunnel to the Raspberry Pi. This Worker does not proxy robot commands and does not replace an Access policy on the dashboard hostname.

## Configure

1. Create the self-hosted Access application and Tunnel route first.
2. Copy `wrangler.jsonc` values into a non-public environment-specific Wrangler config:
   - `TEAM_DOMAIN`: `https://YOUR_TEAM.cloudflareaccess.com`
   - `POLICY_AUD`: the Access application's audience tag (not a secret, but deployment-specific)
   - `CALLBACK_SCHEME`: the exact iOS URL scheme
3. Add a narrow Worker route such as `robot.example.com/api/mobile/auth*` in that private config or the Cloudflare dashboard.
4. Keep the dashboard hostname protected by Access and enable Protect with Access on the Tunnel route.

```bash
npm ci
npm test
npm run check
npm run deploy:dry-run
npm run deploy
```

Do not put an Access service token, tunnel credential, account API token, or application JWT in `vars`; use Wrangler secrets for actual secrets. `POLICY_AUD` and the team domain identify the verifier target but do not authorize requests by themselves.
