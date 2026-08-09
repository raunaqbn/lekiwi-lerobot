# LeKiwi v0.6.1 cutover and rollback

This checkout is the parallel LeKiwi runtime. It is pinned to upstream tag `v0.6.1`
at commit `7e241bd630a3719a56157a497ce5d08f244784f1`. The existing v0.3.4
checkout, environments, and calibration files are deliberately not modified.

## Installed locations

| Component | Mac | Raspberry Pi |
|---|---|---|
| Source | `/Users/raunaqnaidu/Documents/robotics/lerobot-v061` | `/home/raunaqnaidu/lerobot-v061` |
| Conda environment | `/Users/raunaqnaidu/miniconda3/envs/lerobot061` | `/home/raunaqnaidu/miniconda3/envs/lerobot061` |
| Calibration root | `/Users/raunaqnaidu/.cache/huggingface/lerobot-v061` | `/home/raunaqnaidu/.cache/huggingface/lerobot-v061` |

The copied leader calibration SHA-256 is
`b7275c47d27710ca9f50588ea0598a787324cbcb59f79382a5ea544c1f8fd1a1`.
The copied follower calibration SHA-256 is
`ef8139e817de906f7cca055cb2c763492e6713c1a53276d1676e81e5fc4ea347`.

## Preflight

1. Lift the robot so all three wheels are clear of the floor. Keep hands and
   cables out of the arm and wheel travel.
2. Power the Raspberry Pi, follower servo rail, cameras, leader arm, and base.
3. Confirm the Mac and Pi can reach each other at `10.0.0.104`.
4. Do not run standalone diagnostics while teleoperation is active. The live
   feed is embedded in teleoperation so each serial bus has exactly one owner.

## Start v0.6.1

In a terminal connected to the Pi:

```bash
export HF_LEROBOT_HOME=/home/raunaqnaidu/.cache/huggingface/lerobot-v061
cd /home/raunaqnaidu/lerobot-v061
/home/raunaqnaidu/miniconda3/envs/lerobot061/bin/python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=anton
```

Leave that process running. It owns the nine-motor follower bus and serves the
cached follower diagnostics API at `http://10.0.0.104:8091/api/state`.

In a focused Mac terminal:

```bash
export HF_LEROBOT_HOME=/Users/raunaqnaidu/.cache/huggingface/lerobot-v061
cd /Users/raunaqnaidu/Documents/robotics/lerobot-v061
/Users/raunaqnaidu/miniconda3/envs/lerobot061/bin/python examples/lekiwi/teleoperate.py
```

The Mac process owns the six-motor leader bus, starts Rerun, and serves the
aggregate dashboard at `http://127.0.0.1:8090`. Keep Terminal focused for the
pulse keyboard backend: `W/S` forward/back, `A/D` strafe, `Z/X` rotate,
`R/F` speed, and `Ctrl+C` to stop. A key command expires about 0.35 seconds
after its final repeat.

The dashboard uses server-published, calibration-aware joint radians. The CAD
is anchored by default. “Estimated chassis motion” enables visualization-only,
drift-prone wheel odometry; “Reset odometry” changes only the displayed origin.

## Lifted validation checklist

- Both APIs report `schema_version: 2.0` and protocol
  `lekiwi-v061-live-telemetry-v1`.
- The aggregate dashboard reports 15 motors and two cameras.
- Base camera is upright; wrist camera is rotated 90 degrees.
- Move each leader joint independently and confirm the physical follower and
  identically named CAD joint move in the same direction.
- Briefly test `W/S`, `A/D`, `Z/X`, `R/F`, release expiry, and `Ctrl+C`.
- Verify the dashboard changes while teleoperation remains responsive and that
  a feed loss marks the model stale within two seconds.
- Run lifted for ten minutes. Reject cutover on a watchdog trip, serial-bus
  collision, or control-loop gap over 500 ms.

Only after those checks pass should the robot be lowered for a short,
low-speed floor test. Validate odometry direction but do not treat it as an
absolute localization source.

## Rollback

Press `Ctrl+C` in the Mac teleoperation terminal, then in the Pi host terminal.
After both v0.6.1 processes exit, start the previous v0.3.4 Pi host and Mac
teleoperation from their original checkout and environments. No calibration
copy-back is required because the v0.3.4 files were never changed.

## Maintenance diagnostics

Standalone diagnostics remains available when teleoperation is stopped:

```bash
cd /home/raunaqnaidu/lerobot-v061
export HF_LEROBOT_HOME=/home/raunaqnaidu/.cache/huggingface/lerobot-v061
/home/raunaqnaidu/miniconda3/envs/lerobot061/bin/python -m lerobot.robots.lekiwi.diagnostics \
  --serial-port=/dev/serial/by-id/usb-1a86_USB_Single_Serial_5A7A055267-if00 \
  --host=0.0.0.0 --http-port=8091 --no-open
```

If a bus lease is held by teleoperation, standalone diagnostics must not open
the device. Use the embedded feed or stop teleoperation first.
