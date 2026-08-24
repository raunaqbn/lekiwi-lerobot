# LeKiwi Diagnostics launch kit

## Positioning

**One-line description:** Understand your LeKiwi before you move it: leader and follower motor health, power, battery confidence, cameras, controls, and a clickable CAD twin in one local-first dashboard.

**Best first audience:** LeKiwi and LeRobot builders debugging servo buses, power rails, calibration, or leader-to-follower teleoperation.

**Why it is different:** The real-time process remains the only serial-bus owner. The dashboard observes cached telemetry, labels leader and follower sources separately, and explains evidence instead of turning every missing reading into a generic fault.

**Primary action:** [Try the interactive sample robot](https://raunaqbn.github.io/lekiwi-lerobot/demo/), then run diagnostics locally.

## Short launch post

I open-sourced the LeKiwi diagnostics tool I wanted while bringing up my own robot.

It auto-discovers the motor bus, keeps leader and follower readings separate, distinguishes offline vs unpowered vs fault, estimates the follower battery without pretending voltage is exact state-of-charge, and maps live motor state onto the actual LeKiwi CAD in Three.js.

The serial bus stays local to the robot. The public demo is synthetic and safe to explore:

- Demo: https://raunaqbn.github.io/lekiwi-lerobot/demo/
- Source: https://github.com/raunaqbn/lekiwi-lerobot

I would especially value feedback from people who have debugged Feetech buses or built LeKiwi/SO-101 setups.

## Hacker News title

`Show HN: A local-first diagnostics and 3D telemetry deck for LeKiwi robots`

## Community post

### Open-source LeKiwi diagnostics: dual-arm telemetry, power diagnosis, and CAD twin

I built an open-source diagnostics and teleoperation dashboard for LeKiwi because the usual bring-up loop—small serial scripts, ambiguous voltages, and several processes competing for the bus—made failures hard to reason about.

The app shows the leader and follower as separate sources, reads motor voltage/temperature/current/torque/status, calls out an unpowered servo rail separately from an offline controller, provides a deliberately low-confidence follower battery range, and renders the LeKiwi URDF/CAD as a clickable Three.js twin.

The architecture is local-first: the control process owns the serial bus and the browser reads cached snapshots. The public Pages demo uses only synthetic telemetry and cannot control hardware.

I am looking for feedback on additional motor failure modes, controller variants, and installation friction:

- Interactive demo: https://raunaqbn.github.io/lekiwi-lerobot/demo/
- Repository: https://github.com/raunaqbn/lekiwi-lerobot

## Suggested channels

1. LeRobot Discord/forum or the community channel where LeKiwi builders already ask bring-up questions.
2. GitHub repository topics, screenshots, release notes, and Discussions.
3. `r/robotics`, with a technical build note rather than a promotional repost.
4. Hacker News as a concise Show HN after the demo URL is stable.
5. LinkedIn or X with one dashboard screenshot and the interactive demo as the main link.

Post to one community at a time, answer setup questions, and fold repeated friction into the onboarding guide before broadening distribution.
