# LeKiwi iOS operations and release guide

## Architecture

```text
iOS app
  └─ Native system authentication + Keychain Access JWT
      └─ https://robot.example.com
          ├─ /api/mobile/auth* → Cloudflare Worker (JWT verification + app callback)
          └─ all other paths → existing Cloudflare Tunnel
              └─ Raspberry Pi live diagnostics service
                  └─ camera cache + telemetry cache + TeleopControlBridge
                      └─ 30 Hz robot owner loop
```

There is one public hostname, one Cloudflare Access application, and one robot-bus owner. The edge
Worker is routed only to `/api/mobile/auth*`; it does not proxy or modify the dashboard, streams,
telemetry, or controls. The app does not open a new serial connection and does not use
`mobile_gateway.py`.

The Worker source of truth is `cloudflare/lekiwi-mobile-auth`. Its example values must be replaced
in an environment-specific configuration. The Worker validates the assertion's
RS256 signature, issuer, and audience using Cloudflare Access's published keys before returning it
to the registered app callback.

The deployed backend source of truth is the `lerobot-v061` checkout:

- `src/lerobot/robots/lekiwi/live_diagnostics.py` defines telemetry, MJPEG, and control routes.
- `src/lerobot/robots/lekiwi/static/lekiwi_diagnostics.js` documents the browser's control cadence
  and request headers.
- `src/lerobot/robots/lekiwi/lekiwi_host.py` owns the follower loop and its exclusive base bridge.

## Authentication lifecycle

1. On launch, the app checks the iOS Keychain for an existing Cloudflare Access application JWT.
2. If no valid session exists, `ASWebAuthenticationSession` opens the protected
   `/api/mobile/auth` route in the secure system sign-in window.
3. Cloudflare redirects to Google. Face ID and Google passkeys run in the system authentication
   context instead of the app's `WKWebView`.
4. After Access authenticates the request, the edge Worker verifies `Cf-Access-Jwt-Assertion` and
   returns it through a state-verified custom URL callback configured by the app.
5. The app stores the application JWT in Keychain and sends it using Cloudflare's supported
   `cf-access-token` request header.
6. The app verifies that `/api/state` returns JSON from the configured dashboard host before exposing the
   operating interface.
7. A redirect, HTML response, 401, or 403 from a protected route is treated as an expired session.
   Motion is stopped, streams close, and the login page returns.

Sign-out stops motion, disables the control bridge, closes both streams, removes the Keychain JWT,
and clears cookies scoped to the configured host and the Cloudflare Access team domain.

No Cloudflare client secret or robot bearer token is embedded in the app or TestFlight binary.

## Camera and telemetry behavior

Only the selected MJPEG camera is open, reducing radio and server load. Switching cameras cancels
the old stream before starting the new one. The parser accepts split JPEG markers and caps its
buffer at 8 MiB so a malformed stream cannot grow memory without bound.

Telemetry starts with `/api/state`, then follows `/api/stream`. The app reconnects the event stream
after transient failures. State samples drive the nine-motor 3D twin bundled in the application;
the twin remains usable while a camera reconnects. The app preserves the backend's
`joint_frame` and `joint_position_rad` fields so the CAD uses the same calibrated pose as the web
dashboard. Operators open the twin in a dedicated sheet so it never obscures the camera or motion
controls. The sheet provides explicit rotate, tilt, zoom, and reset buttons in addition to direct
dragging.

Readiness is follower-specific. The aggregate `connected` field also includes the optional leader
arm and may be false while the follower is fresh, powered, healthy, and fully controllable. The iOS
status and control gate therefore use `sources.follower.connected`, follower staleness, and
`control.available/permitted`; leader absence never disables follower operation.

## Direction-button mapping

| Button                 | Dashboard key |
| ---------------------- | ------------- |
| Forward / Back         | W / S         |
| Left / Right           | A / D         |
| Turn left / Turn right | Z / X         |

After the operator taps **Enable**, each direction tap creates a 420 ms bounded movement. The active
key is refreshed every 160 ms, inside the backend's 350 ms expiry window, and receives an
`active: false` pulse when the step ends. Starting another step replaces the current direction.

Speed levels exactly match the deployed `TeleopControlBridge`:

| Level  | Translation | Rotation | Backend index |
| ------ | ----------: | -------: | ------------: |
| Slow   |    0.08 m/s |    25°/s |             0 |
| Medium |    0.16 m/s |    50°/s |             1 |
| Fast   |    0.25 m/s |    75°/s |             2 |

## Follower-arm mapping

Tapping a joint directly on the 3D model selects the matching control target. Tapping base-wheel
geometry switches back to Omni base mode. Changing targets releases only the active movement pulse;
it keeps arm takeover and every cached joint target engaged so loaded joints such as shoulder lift
continue holding their last commanded position.

| App target    | Follower motor | Dashboard joint key     |
| ------------- | -------------: | ----------------------- |
| Shoulder pan  |              1 | `arm_shoulder_pan.pos`  |
| Shoulder lift |              2 | `arm_shoulder_lift.pos` |
| Elbow flex    |              3 | `arm_elbow_flex.pos`    |
| Wrist flex    |              4 | `arm_wrist_flex.pos`    |
| Wrist roll    |              5 | `arm_wrist_roll.pos`    |
| Gripper       |              6 | `arm_gripper.pos`       |

Arm mode enables `/api/control/arm`. Each −/+ tap refreshes the selected `/api/control/joint` pulse
every 160 ms for one 420 ms step. Tapping **Stop** sends the same latched Stop used by base mode.

## Motion invariants

- The app never calls the motor bus directly.
- Movement cannot be enabled unless live follower telemetry says control is permitted.
- The optional leader-arm connection does not gate follower controls.
- Changing base/arm mode or selected joint releases the active pulse without globally stopping,
  disarming, or clearing follower-arm position targets.
- A control failure disables the UI and clears any active step.
- The Stop buttons send Stop followed by `enabled: false`.
- Backgrounding, sign-out, and Access expiry stop motion and close streams.
- The Raspberry Pi owner loop independently expires stale intent after 350 ms.
- The physical power cutoff remains the emergency stop.

Before remote operation, confirm all people are visible, the robot has clearance, and someone near
the robot can remove power. Do not rely on camera coverage as proof that the full operating area is
clear.

## Verification checklist

Run before every upload:

```bash
cd ios/LeKiwiController
xcodegen generate
xcodebuild test \
  -project LeKiwiController.xcodeproj \
  -scheme LeKiwiController \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Verify the Worker before testing on a physical iPhone:

```bash
cd cloudflare/lekiwi-mobile-auth
npm test
npm run check
npm run deploy:dry-run
```

Then verify on a physical iPhone:

1. Fresh install opens the login page.
2. Successful Access login reaches Operate without asking for a gateway or token.
3. Front and wrist feeds both show current frames.
4. The **3D** button opens a separate model sheet with rotate, tilt, zoom, and reset buttons.
5. Tapping model geometry updates the named motor ID and temperature/voltage strip.
6. Enable movement and verify each Omni base direction matches the web dashboard direction.
7. Each of the six follower joints selects the expected motor ID and responds to short −/+ taps.
8. Each step stops after its bounded pulse, and **Stop** immediately disables movement.
9. Locking the phone or switching apps stops motion.
10. Sign-out returns to login and a subsequent API request is blocked until re-authentication.

## Troubleshooting

### Login completes but the app returns to sign-in

- Confirm `https://robot.example.com/api/state` (using your hostname) works in Safari for the same account.
- Check that the Access policy permits that identity.
- Confirm the `lekiwi-mobile-auth` Worker is deployed on the
  `robot.example.com/api/mobile/auth*` route using your hostname.
- Confirm the Worker's `TEAM_DOMAIN` and `POLICY_AUD` match the existing Access application.
- If the login page reports a nearby-device Bluetooth passkey error, confirm the app is Build 3 or
  newer; Build 2 used an embedded `WKWebView` and could not use Google's on-device passkey route.

### Telemetry works but video is blank

- Open the matching `/api/cameras/<name>/stream` route in the web dashboard.
- Confirm the dashboard reports a recent frame for that camera.
- Switching to the other camera forces a clean MJPEG reconnect.

### Enable is unavailable and controls are paused

Read **Settings → Control readiness**. The backend blocks control when follower telemetry is stale,
servo power is missing, a critical motor fault exists, or fewer than all nine motors respond.

### Motion starts in the wrong direction

Stop with the physical cutoff, then compare W/A/S/D/Z/X behavior in the web dashboard. Update and
test `JoystickCommandMapper` before operating again; do not compensate by mentally reversing a
direction button.

## TestFlight release

1. Increment `CURRENT_PROJECT_VERSION` in `project.yml` and regenerate the project.
2. Run the simulator test suite and a signed Release build.
3. Archive with the `generic/platform=iOS` destination.
4. Export using the App Store Connect upload method.
5. Upload the IPA, wait for App Store Connect processing, and add the build to **LeKiwi Internal**.
6. Record the processed build number and test notes in the release handoff.

Build 2 release notes:

- Uses the configured protected dashboard backend.
- Adds Cloudflare Access sign-in and session expiry handling.
- Streams the real front/wrist MJPEG feeds.
- Uses the existing SSE telemetry and dead-man control routes.
- Removes the retired pairing-token/WebSocket gateway flow.

Build 3 release notes:

- Replaces embedded web login with `ASWebAuthenticationSession` for Google passkey and Face ID support.
- Adds a protected Cloudflare Worker callback bridge at `/api/mobile/auth` without changing the
  existing Access policy or Raspberry Pi service.
- Stores the Access application JWT in Keychain and authenticates all streams and commands with
  Cloudflare's `cf-access-token` header.

Build 4 release notes:

- Fixes an immediate false session-expiry after login by accepting both the outer MJPEG
  `multipart/x-mixed-replace` response and the `image/jpeg` MIME-part responses reported by
  `URLSession`.
- Adds a production integration test that authenticates state and telemetry, receives real front
  and wrist camera frames, and verifies a safe Stop control request through Cloudflare Access.

Build 5 release notes:

- Fixes the false **Offline** state and disabled controls when the optional leader arm is absent but
  the follower owner loop is healthy and permitted.
- Adds explicit Omni base / Follower arm modes and named dead-man control for all six follower joints.
- Adds camera-only, dismissible 3D overlay, and camera/3D split layouts.
- Preserves the calibrated CAD joint frame so the live twin matches the backend pose.

Build 6 release notes:

- Replaces the fused camera/3D layouts with an explicit 3D inspection sheet.
- Removes floating health dots and keeps healthy model geometry neutral.
- Adds precise model rotate, tilt, zoom, and reset buttons.
- Replaces Hold plus joysticks with tap-to-enable, bounded direction steps, and visible Stop actions.
- Restructures portrait and landscape layouts so controls remain inside the safe area.
