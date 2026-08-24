# Deployment guide

LeKiwi has two deployment planes with different safety requirements:

1. **Robot plane:** Python on the Raspberry Pi or directly connected computer. It owns USB serial, cameras, watchdogs, and the 30 Hz loop.
2. **Presentation plane:** static documentation and optional authentication helpers on GitHub Pages, Cloudflare, Vercel, or another web host.

Do not deploy the robot plane to a serverless platform. It cannot access the robot's devices and provides no real-time guarantee.

## Raspberry Pi with systemd

Install the checkout and environment as the non-root user that will run the robot:

```bash
git clone https://github.com/raunaqbn/lekiwi-lerobot.git ~/lekiwi
cd ~/lekiwi
uv sync --locked --extra lekiwi
mkdir -p ~/.config/lekiwi
cp deploy/systemd/host.env.example ~/.config/lekiwi/host.env
```

Edit `host.env` with persistent `/dev/serial/by-id/...` and `/dev/v4l/by-id/...` paths. Then install the template unit (replace `$USER` in the instance name, not inside the unit):

```bash
sudo cp deploy/systemd/lekiwi-host@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "lekiwi-host@$USER.service"
systemctl status "lekiwi-host@$USER.service"
```

The user must belong to `dialout` and `video`. The service deliberately uses a read-only home except for LeRobot cache/config paths. If your checkout is not `~/lekiwi`, install a systemd override instead of editing the tracked template.

## Docker (bench diagnostics)

Docker is useful for reproducible diagnostics, but host device paths and permissions still matter:

```bash
docker build -f deploy/docker/Dockerfile -t lekiwi-diagnostics .
docker run --rm -it \
  --device=/dev/ttyACM0 \
  -p 127.0.0.1:8090:8090 \
  -v "$HOME/.cache/huggingface/lerobot:/data" \
  -e HF_LEROBOT_HOME=/data \
  lekiwi-diagnostics
```

Do not use `--privileged`. Stop any host process that owns the same controller before starting the container.

## Private remote dashboard with Cloudflare

First create a Cloudflare Access self-hosted application with a deny-by-default policy. Then create a Tunnel route from your hostname to `http://127.0.0.1:8091` on the Pi. Enabling **Protect with Access** makes `cloudflared` validate the Access token at the origin boundary.

For a locally managed tunnel, copy [`cloudflare/tunnel-config.yml.example`](./cloudflare/tunnel-config.yml.example), replace the placeholders outside the repository, and validate it:

```bash
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://robot.example.com
cloudflared tunnel run lekiwi
```

The final catch-all rule is intentional. Never commit the tunnel credential JSON or token. The optional [`cloudflare/lekiwi-mobile-auth`](../cloudflare/lekiwi-mobile-auth) Worker exchanges an already verified Access application JWT into the native iOS callback; it is not a substitute for Access on the dashboard route.

Official references: [Tunnel setup](https://developers.cloudflare.com/tunnel/setup/), [Access self-hosted applications](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/), and [locally managed configuration](https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/).

## Static docs on Cloudflare Workers

The `site` directory is self-contained. From it:

```bash
cd site
npx wrangler deploy
```

`site/wrangler.jsonc` uses Workers Static Assets only. It contains no robot API route or secret.

## Static docs on Vercel

Import the GitHub repository in Vercel and set **Root Directory** to `site`. No framework preset or build command is required; `site/vercel.json` supplies caching and security headers. This deployment is documentation/demo only.

## GitHub Pages or any static host

The included Pages workflow publishes `site` on pushes to `main`. Enable **Settings → Pages → Source: GitHub Actions** once. For another host, upload the contents of `site/` as the document root.

## Preflight before remote access

- Lift all three wheels and clear the arm workspace.
- Confirm a physical power cutoff is reachable.
- Verify leader and follower voltages are labeled separately.
- Confirm Stop releases dashboard arm takeover before using the leader.
- Test stale telemetry, browser close, network loss, and host restart behavior.
- Restrict Access to named operators and use short sessions.
- Do not cache `/api/*`, MJPEG, or SSE responses at a CDN.
