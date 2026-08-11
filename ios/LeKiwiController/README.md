# LeKiwi for iOS

LeKiwi for iOS is the native field controller for the existing dashboard at
[`robot.offerhack.io`](https://robot.offerhack.io). It shows the front or wrist camera, opens the
official LeKiwi spatial twin in a dedicated inspection sheet, streams live motor health, and
exposes fail-safe omniwheel-base and per-joint follower-arm controls.

The app does **not** run a second gateway or require a pairing token. It authenticates through the
same Cloudflare Access application. A narrowly routed Cloudflare Worker completes the native login;
all dashboard data and controls continue through the same Raspberry Pi owner loop as the web app.

## Operator quick start

1. Install the current TestFlight build.
2. Tap **Sign in with Cloudflare Access**.
3. Complete the same identity-provider login used for `robot.offerhack.io`.
4. Confirm the connection chip reads **Robot ready** and the camera label reads **Camera live**.
5. Choose the front or wrist feed. Tap **3D** to inspect the robot model separately.
6. Choose **Omni base** or **Follower arm**. Arm mode names the selected joint and motor ID before
   any input is accepted.
7. Tap **Enable**, then tap a labeled direction for one short movement. Tap **Stop** to disable
   remote control.

The app automatically returns to sign-in when its Access session expires. The preview option uses
illustrative telemetry and never sends network control commands.

## Existing service contract

| Function | Existing dashboard route | iOS behavior |
| --- | --- | --- |
| Native sign-in | `GET /api/mobile/auth` | Edge Worker verifies and returns the Access application JWT through the registered iOS callback |
| Initial state | `GET /api/state` | Validates login and hydrates health/twin state |
| Live state | `GET /api/stream` | Consumes `state` server-sent events |
| Front camera | `GET /api/cameras/front/stream` | Parses the existing MJPEG stream |
| Wrist camera | `GET /api/cameras/wrist/stream` | Parses the existing MJPEG stream |
| Control enable | `POST /api/control/enable` | Enables the owner-loop control bridge until Stop, interruption, or backgrounding |
| Arm takeover | `POST /api/control/arm` | Selects safe browser control of the follower arm |
| Joint jog | `POST /api/control/joint` | Pulses one named joint in the selected −/+ direction |
| Speed | `POST /api/control/speed` | Uses backend levels 0–2 |
| Base movement | `POST /api/control/base` | Pulses W/A/S/D/Z/X every 160 ms |
| Stop | `POST /api/control/stop` | Sent on Stop, interruption, sign-out, and backgrounding |

Every control POST is JSON with `X-LeKiwi-Control: dashboard-v1`, matching the web dashboard. The
iOS app sends the Access application JWT using Cloudflare's supported `cf-access-token` header.
It is stored in the iOS Keychain and is never built into the app. `X-LeKiwi-Control` is part of the
control protocol, not an authentication secret.

## Build and test

```bash
cd ios/LeKiwiController
xcodegen generate
xcodebuild test \
  -project LeKiwiController.xcodeproj \
  -scheme LeKiwiController \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Build settings are generated from `project.yml`. Increment `CURRENT_PROJECT_VERSION` before each
TestFlight upload.

For operational details, authentication behavior, safety invariants, troubleshooting, and the
release procedure, see [OPERATIONS.md](OPERATIONS.md).

## Safety boundary

The server expires base or joint intent after 350 ms without a fresh pulse. Each direction tap is
bounded to a short pulse, and the app sends Stop when the operator disables movement, the scene
leaves the foreground, a control request fails, authentication expires, or the user signs out.
These are software safeguards, not an emergency stop. The operator must stay near the robot and
retain access to its physical power cutoff.
