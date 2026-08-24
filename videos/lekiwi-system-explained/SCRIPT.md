# SCRIPT — lekiwi-system-explained

**Voice:** Marcia (HeyGen)
**Voice settings:** provider default
**Voice direction:** Calm technical operator briefing. Precise, unhurried, low hype. Brief pause after each contrast.

---

## Line 1 — Online is not understood (Frame 1)

**Time:** 0.0 – 10.0s
**Delivery:** Open with concern, then land “actually observed.”

    A robot can be online while its commands are idle, powered while one bus is dark, and connected while the operator is looking at the wrong voltage. Good diagnostics must say what was actually observed.

## Line 2 — One owner (Frame 2)

**Time:** 10.0 – 23.0s
**Delivery:** State the rule simply; give each node equal weight.

    LeKiwi solves that with one rule: one process owns each serial bus. The leader computer samples six motors. The Raspberry Pi owns nine follower motors and the cameras. Every web request reads an immutable cached snapshot.

## Line 3 — Source-labeled truth (Frame 3)

**Time:** 23.0 – 36.0s
**Delivery:** Make the voltage comparison reassuring, then sharpen the final contrast.

    That cache keeps sources separate. Six leader servos at about five volts can be healthy while the follower reports a three-cell rail near ten and a half. Fault, unpowered, offline, and not applicable are different diagnoses—not different shades of red.

## Line 4 — Battery band (Frame 4)

**Time:** 36.0 – 48.0s
**Delivery:** Emphasize estimate and cannot.

    Battery state is an estimate, not a stopwatch. The dashboard takes the median of readable follower voltages and maps it to a deliberately wide three-cell confidence band. Motor calibration maps position; it cannot reveal chemistry, load sag, aging, or remaining runtime.

## Line 5 — Twin and takeover (Frame 5)

**Time:** 48.0 – 62.0s
**Delivery:** Descriptive first sentence, operational warning in the second.

    The same calibrated positions drive a clickable Three.js twin built from the LeKiwi URDF and CAD meshes. But browser arm mode is active control: it replaces manual leader goals with cached hold or jog targets. Press Stop and release takeover before expecting the leader to drive again.

## Line 6 — Cloud boundary (Frame 6)

**Time:** 62.0 – 75.0s
**Delivery:** Clear, architectural cadence; no marketing inflection on platform names.

    Deployment preserves that boundary. Systemd keeps the owner loop beside USB and cameras. Cloudflare Access and an outbound Tunnel can protect the cached dashboard. Vercel, Workers, or GitHub Pages host the guide—not the motor loop. Serverless has no serial bus and no real-time guarantee.

## Line 7 — Open and stoppable (Frame 7)

**Time:** 75.0 – 85.0s
**Delivery:** Inviting, then sober on the final safety line.

    The complete stack—Python host, dashboard, 3D assets, iOS client, deployment templates, tests, licenses, and this guide—is open under Apache Two. Run the demo, inspect every boundary, then test lifted with a physical power cutoff in reach.
