# LeKiwi operator runbook

This runbook covers the local-first diagnostics and teleoperation stack in this fork. It intentionally uses hostnames, environment variables, and persistent device paths instead of a maintainer's private network or USB serial numbers.

## Preflight

1. Lift all three wheels and clear the full arm envelope.
2. Keep the physical servo/base power cutoff within reach.
3. Power the Pi, follower servo rail, leader arm, cameras, and base.
4. Resolve the Pi as `lekiwi.local` or set `LEKIWI_HOST` to its private address.
5. Use `ls -l /dev/serial/by-id /dev/v4l/by-id` to identify stable device paths.
6. Never run standalone diagnostics while the same bus is owned by teleoperation.

## Raspberry Pi host

```bash
cd ~/lekiwi
export LEKIWI_FOLLOWER_PORT=/dev/serial/by-id/<follower-controller>
export LEKIWI_FRONT_CAMERA=/dev/v4l/by-id/<front-camera>
export LEKIWI_WRIST_CAMERA=/dev/v4l/by-id/<wrist-camera>
export LEKIWI_DIAGNOSTICS_HOST=0.0.0.0  # trusted LAN or authenticated tunnel only
uv run --extra lekiwi python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=lekiwi
```

The process owns the nine-motor follower bus and exposes cached diagnostics at `http://lekiwi.local:8091/api/state`. A powered USB adapter with no servo replies is reported as likely **servo rail off**, not nine independent motor faults.

## Leader computer

```bash
cd ~/lekiwi
export LEKIWI_HOST=lekiwi.local
export LEKIWI_LEADER_PORT=/dev/serial/by-id/<leader-controller>
uv run --extra lekiwi python examples/lekiwi/teleoperate.py --no-rerun
```

The leader process owns the six-motor leader bus and serves the combined dashboard at `http://127.0.0.1:8090`. Leader voltage and follower voltage are separate sources; a 5 V leader and 3S follower can both be healthy.

The dashboard's Follower arm mode is a takeover. It freezes or jogs cached follower targets and intentionally replaces manual leader commands. Select **Stop / Release arm** before expecting leader movement to pass through again.

## Lifted validation

- Both APIs report schema `2.0` and the live telemetry protocol.
- The combined dashboard reports 15 motors: six leader plus nine follower.
- All follower motors have fresh readings, the expected IDs, and roughly consistent rail voltage.
- Front and wrist cameras are correctly oriented.
- Each leader joint moves the identically named follower/CAD joint in the expected direction.
- W/S, A/D, Z/X, speed controls, release expiry, and Stop behave correctly.
- A feed loss becomes stale within two seconds and never masquerades as a live healthy sample.
- A ten-minute lifted run has no bus collision, write exception, watchdog trip, or control-loop gap above 500 ms.

Only after passing should you perform a short, low-speed floor test.

## Standalone maintenance diagnostics

Stop the owner process first:

```bash
uv run --extra lekiwi lerobot-lekiwi-diagnostics \
  --serial-port /dev/serial/by-id/<controller> \
  --host 127.0.0.1 \
  --http-port 8090
```

The serial bus remains read-only with respect to torque and goal positions, but it still requires an exclusive lease. The app remembers the last successful controller and can auto-detect plausible USB serial devices on the next launch.

## Post-session latency traces

Tracing is opt-in and batches JSONL records outside the control loop:

```bash
# Pi
uv run --extra lekiwi python -m lerobot.robots.lekiwi.lekiwi_host \
  --robot.id=lekiwi \
  --host.latency_trace_dir=$HOME/.local/state/lekiwi/latency

# Leader computer
uv run --extra lekiwi python examples/lekiwi/teleoperate.py \
  --latency-trace-dir $HOME/.local/state/lekiwi/latency

# After the session
uv run --extra lekiwi lerobot-lekiwi-latency-report $HOME/.local/state/lekiwi/latency
```

The report separates motor reads/writes, camera capture/encode, diagnostics sampling, network/queue residual, camera decode, leader reads, and Rerun logging. One-way network latency is not claimed without clock-offset measurement.

## Remote access

Do not bind the Flask service directly to the public internet. Follow [`deploy/README.md`](../../deploy/README.md) to put a Cloudflare Access-protected Tunnel or private VPN in front of the Pi. Browser safeguards and software watchdogs are not an emergency stop.
