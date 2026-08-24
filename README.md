<p align="center">
  <img alt="LeKiwi Diagnostics and Teleoperation" src="./media/readme/lerobot-logo-thumbnail.png" width="100%">
</p>

<div align="center">

# LeKiwi Diagnostics + Teleoperation

**A local-first control deck, motor health monitor, and 3D digital twin for LeKiwi.**

[![License](https://img.shields.io/badge/license-Apache--2.0-5ce1e6)](./LICENSE)
[![Security](https://img.shields.io/badge/robot%20control-local--first-a6ff4d)](./SECURITY.md)
[![LeRobot](https://img.shields.io/badge/based%20on-LeRobot-f4d35e)](https://github.com/huggingface/lerobot)

</div>

This repository is an Apache-2.0 fork of [Hugging Face LeRobot](https://github.com/huggingface/lerobot) with a production-minded LeKiwi operator experience. It keeps the serial bus and motor loop on machines physically connected to the robot while making cached telemetry, camera feeds, controls, and the robot's live pose available through a modern browser dashboard.

> [!CAUTION]
> This software can move physical hardware. Start with the wheels lifted, keep a hand on the physical power cutoff, and never treat browser controls or a network tunnel as an emergency stop.

## What is included

- Automatic Feetech bus discovery with remembered ports and baud rates.
- Separate leader and follower telemetry: detection, voltage, temperature, torque, load, current, motion, and status.
- A calibrated battery estimate for the 3S follower pack, including an uncertainty band instead of false precision.
- Clear distinction between `fault`, `unpowered`, `offline`, and `not applicable` states.
- A clickable Three.js digital twin built from the LeKiwi URDF and vendored CAD meshes.
- A single-owner motor architecture: HTTP and SSE handlers read immutable cached snapshots and never open the serial bus.
- Low-latency leader-to-follower teleoperation, dead-man base controls, arm jogging, camera streams, and optional post-session latency traces.
- Native iOS controller source and an optional Cloudflare Access authentication Worker.
- Deployable static documentation for GitHub Pages, Cloudflare Workers/Pages, Vercel, or any static host.

## Architecture and hosting boundary

```text
Leader arm + browser                         Raspberry Pi + follower
┌──────────────────────────┐                ┌──────────────────────────┐
│ teleoperate.py           │  ZMQ 5555/56  │ lekiwi_host             │
│ • leader bus owner       ├───────────────►│ • follower bus owner     │
│ • aggregate dashboard   │◄───────────────┤ • camera owner           │
│ • cached leader state   │                │ • cached diagnostics API │
└──────────────────────────┘                └──────────────────────────┘
          ▲                                             ▲
          │ localhost / protected tunnel                │ USB serial
          └──────── browser or iOS ─────────────────────┘
```

Vercel and Cloudflare can host the documentation and browser assets. They **cannot** own `/dev/ttyACM0`, guarantee a 30 Hz motor loop, or replace the Raspberry Pi host. For remote operation, keep the control service beside the robot and put Cloudflare Tunnel + Access or a private VPN in front of it.

## Quick start: diagnostics only

Python 3.12 and `uv` are recommended.

```bash
git clone https://github.com/raunaqbn/lekiwi-lerobot.git
cd lekiwi-lerobot
uv sync --locked --extra lekiwi
uv run --extra lekiwi lerobot-lekiwi-diagnostics
```

Open [http://127.0.0.1:8090](http://127.0.0.1:8090). The app probes plausible USB serial adapters automatically and remembers the last working controller. To inspect the UI without hardware:

```bash
uv run --extra lekiwi lerobot-lekiwi-diagnostics --demo
```

Useful explicit options:

```bash
uv run --extra lekiwi lerobot-lekiwi-diagnostics \
  --serial-port /dev/serial/by-id/<your-controller> \
  --follower-url http://lekiwi.local:8091 \
  --no-open
```

Standalone diagnostics is read-only, but it still needs exclusive serial access. Stop teleoperation first; while teleoperation is active, use its embedded cached dashboard instead.

## Quick start: follower host + leader teleoperation

On the Raspberry Pi:

```bash
git clone https://github.com/raunaqbn/lekiwi-lerobot.git ~/lekiwi
cd ~/lekiwi
uv sync --locked --extra lekiwi
export LEKIWI_FOLLOWER_PORT=/dev/serial/by-id/<follower-controller>
# Required for a trusted LAN client or an authenticated local tunnel.
export LEKIWI_DIAGNOSTICS_HOST=0.0.0.0
uv run --extra lekiwi python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=lekiwi
```

On the leader computer:

```bash
git clone https://github.com/raunaqbn/lekiwi-lerobot.git ~/lekiwi
cd ~/lekiwi
uv sync --locked --extra lekiwi
export LEKIWI_HOST=lekiwi.local
export LEKIWI_LEADER_PORT=/dev/serial/by-id/<leader-controller>
uv run --extra lekiwi python examples/lekiwi/teleoperate.py --no-rerun
```

The leader process serves the combined dashboard at `http://127.0.0.1:8090`; the Pi serves follower-only cached telemetry at `http://lekiwi.local:8091`. The dashboard's arm takeover intentionally overrides leader goals while enabled. Press **Stop / Release arm** before expecting the manual leader arm to drive the follower again.

## Configuration

| Setting                   | Default                  | Purpose                                                                |
| ------------------------- | ------------------------ | ---------------------------------------------------------------------- |
| `LEKIWI_FOLLOWER_PORT`    | `/dev/ttyACM0`           | Follower Feetech controller; use `/dev/serial/by-id/...` in production |
| `LEKIWI_LEADER_PORT`      | required by teleoperator | Leader arm controller                                                  |
| `LEKIWI_HOST`             | `lekiwi.local`           | Pi hostname or address                                                 |
| `LEKIWI_ROBOT_ID`         | `lekiwi`                 | Calibration identity                                                   |
| `LEKIWI_DIAGNOSTICS_HOST` | `127.0.0.1`              | HTTP bind; the Pi service uses `0.0.0.0` only behind a firewall/tunnel |
| `LEKIWI_FRONT_CAMERA`     | `/dev/video0`            | Front camera device                                                    |
| `LEKIWI_WRIST_CAMERA`     | `/dev/video2`            | Wrist camera device                                                    |
| `HF_LEROBOT_HOME`         | LeRobot cache default    | Calibration and remembered diagnostics settings                        |

The diagnostics memory file is stored under `HF_LEROBOT_HOME` (or the default LeRobot cache). It contains device paths and the follower URL, never credentials.

## Deployment choices

| Goal                     | Recommended deployment           | What runs there                     |
| ------------------------ | -------------------------------- | ----------------------------------- |
| Local bench diagnostics  | Python CLI on Mac/Linux/Pi       | Serial probing + dashboard          |
| Persistent robot service | systemd on the Pi                | Motor owner + cameras + cached API  |
| Remote private access    | Cloudflare Tunnel + Access       | Authenticated route to the Pi       |
| Public docs/demo         | GitHub Pages, Cloudflare, Vercel | Static HTML only                    |
| Native field controller  | Xcode + optional auth Worker     | iOS client; commands still go to Pi |

See [`deploy/README.md`](./deploy/README.md) for systemd, Docker, Cloudflare, Vercel, and generic static-host instructions. The detailed visual guide lives in [`site/index.html`](./site/index.html).

## Development

```bash
uv sync --locked --extra test --extra dev --extra lekiwi
uv run --extra test --extra lekiwi pytest -q tests/robots/test_lekiwi_diagnostics.py tests/robots/test_lekiwi_live_diagnostics.py
uv run --extra dev pre-commit run --all-files
```

The browser dashboard has no npm runtime dependency: Three.js and URDF Loader are vendored with their licenses so the app works offline. The Cloudflare Worker is the only Node subproject.

## Security model

- Do not bind the dashboard to a public interface without authentication and TLS.
- The `X-LeKiwi-Control` header is a protocol marker, **not authentication**.
- Cloud static hosts are for docs/assets, not motor control.
- Cloudflare Access tokens belong in the iOS Keychain or request headers, never source code.
- Hardware watchdogs, bounded pulses, and cached telemetry reduce risk but do not replace a physical E-stop.

Report vulnerabilities privately using this repository's [GitHub Security Advisory form](https://github.com/raunaqbn/lekiwi-lerobot/security/advisories/new). Read the full [security policy](./SECURITY.md) before exposing a robot endpoint.

## License and upstream credit

The repository is licensed under [Apache License 2.0](./LICENSE). It is derived from Hugging Face's LeRobot and retains upstream history, notices, and file-level copyright headers. Vendored Three.js is MIT; URDF Loader and the included LeKiwi CAD export are Apache-2.0. See [NOTICE](./NOTICE) and [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).

LeRobot citation:

```bibtex
@misc{cadene2024lerobot,
  title        = {LeRobot: State-of-the-art Machine Learning for Real-World Robotics in PyTorch},
  author       = {Cadene, Remi and others},
  year         = {2024},
  howpublished = {\url{https://github.com/huggingface/lerobot}}
}
```

This community fork is not an official Hugging Face product and does not grant rights to Hugging Face trademarks.
