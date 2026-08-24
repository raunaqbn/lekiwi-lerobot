# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

LeKiwi builders, robotics students, researchers, educators, and maintainers who need to understand a robot before moving it. Users range from first-time LeRobot builders to experienced operators debugging serial buses, servo power, calibration, or teleoperation.

## Product Purpose

LeKiwi Diagnostics makes the complete robot state understandable from one local-first operator deck. Success means a user can identify which leader or follower component is connected, powered, healthy, stale, or faulty without assembling one-off Python scripts, and can move from a safe simulated preview to their own robot with clear hardware boundaries.

## Positioning

Unlike a generic device dashboard, LeKiwi Diagnostics combines bus-owner-safe telemetry, source-labeled leader and follower readings, honest battery confidence, and the official robot CAD in one interface. The motor process remains the only owner of each serial bus; browsers observe cached state rather than competing with the control loop.

## Operating Context

The product runs beside the robot on a Mac, Linux computer, or Raspberry Pi and is viewed in a modern browser. The leader controller is commonly connected locally over USB while follower telemetry is published by a Raspberry Pi. A public hosted preview uses synthetic telemetry only; real motor access remains local to the robot.

## Capabilities and Constraints

- Automatic Feetech bus discovery with remembered port and baud-rate settings.
- Separate leader and follower motor state, voltage, temperature, torque, current, motion, and fault evidence.
- Voltage-only 3S follower battery estimate with an uncertainty range.
- Clickable Three.js digital twin built from the vendored LeKiwi URDF and CAD meshes.
- Read-only standalone diagnostics and owner-loop-integrated teleoperation controls.
- Static hosting can demonstrate the interface but cannot access USB devices or provide a real-time motor loop.
- Physical movement requires local setup, supervision, a clear workspace, lifted wheels for initial tests, and access to the power cutoff.

## Brand Commitments

The product name is “LeKiwi Diagnostics + Teleoperation.” The voice is direct, technically honest, and hardware-aware. It is an Apache-2.0 community fork of Hugging Face LeRobot and must not imply official Hugging Face endorsement.

## Evidence on Hand

- Working diagnostics and teleoperation implementation under `src/lerobot/robots/lekiwi/`.
- Real dashboard captures under `media/readme/`.
- Vendored official LeKiwi URDF and CAD meshes under `src/lerobot/robots/lekiwi/static/models/lekiwi/`.
- Focused tests under `tests/robots/`.
- Public repository, release, and GitHub Pages deployment.
- No testimonials, adoption metrics, or performance benchmarks are currently established; future marketing must not fabricate them.

## Product Principles

1. Show source and evidence, not a generic fault light.
2. Keep one owner for every motor bus.
3. Separate preview, observation, and physical control unmistakably.
4. Get users to trustworthy robot state before teaching advanced operation.
5. Prefer uncertainty bands and recovery guidance over false precision.

## Accessibility & Inclusion

State must be conveyed with text as well as color, controls must remain keyboard accessible, and layouts must work from small mobile screens through desktop workstations.
