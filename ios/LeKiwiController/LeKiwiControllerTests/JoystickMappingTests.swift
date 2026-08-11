import XCTest
@testable import LeKiwiController

final class JoystickMappingTests: XCTestCase {
    func testSpeedLevelsMatchRobotClientLimits() {
        XCTAssertEqual(RobotStore.SpeedLevel.slow.xy, 0.08)
        XCTAssertEqual(RobotStore.SpeedLevel.medium.xy, 0.16)
        XCTAssertEqual(RobotStore.SpeedLevel.fast.xy, 0.25)
        XCTAssertEqual(RobotStore.SpeedLevel.fast.theta, 75)
        XCTAssertEqual(RobotStore.SpeedLevel.fast.index, 2)
    }

    func testSampleStateContainsTheExpectedNineMotors() {
        XCTAssertEqual(GatewayState.sample.sources.follower.motors.count, 9)
        XCTAssertEqual(GatewayState.sample.sources.follower.motors.last?.id, 9)
    }

    func testJoystickMapsToDashboardDeadmanKeys() {
        XCTAssertEqual(
            JoystickCommandMapper.keys(
                translation: CGPoint(x: 0.8, y: -0.9),
                rotation: CGPoint(x: -0.7, y: 0)
            ),
            [.forward, .right, .rotateLeft]
        )
        XCTAssertTrue(
            JoystickCommandMapper.keys(
                translation: CGPoint(x: 0.1, y: -0.1),
                rotation: .zero
            ).isEmpty
        )
    }

    func testArmJointTargetsMatchDashboardControlContract() {
        XCTAssertEqual(ArmJoint.shoulderPan.serverKey, "arm_shoulder_pan.pos")
        XCTAssertEqual(ArmJoint.shoulderLift.serverKey, "arm_shoulder_lift.pos")
        XCTAssertEqual(ArmJoint.elbowFlex.id, 3)
        XCTAssertEqual(ArmJoint.gripper.serverKey, "arm_gripper.pos")
        XCTAssertEqual(JointCommandMapper.direction(jog: CGPoint(x: -0.8, y: 0)), -1)
        XCTAssertEqual(JointCommandMapper.direction(jog: CGPoint(x: 0.8, y: 0)), 1)
        XCTAssertNil(JointCommandMapper.direction(jog: CGPoint(x: 0.1, y: 0)))
    }

    @MainActor
    func testFollowerReadinessDoesNotRequireOptionalLeaderConnection() {
        let store = RobotStore(restoreSession: false)
        var state = GatewayState.sample
        state.demo = false
        state.connected = false
        state.sources.follower.connected = true
        state.sources.follower.stale = false
        state.control?.available = true
        state.control?.permitted = true
        store.state = state
        store.authenticationState = .authenticated

        XCTAssertTrue(store.followerOnline)
        XCTAssertTrue(store.followerReady)
        XCTAssertTrue(store.canArm)
        XCTAssertEqual(store.followerStatusTitle, "Robot ready")
        store.disconnect()
    }

    func testMJPEGParserHandlesSplitFrames() {
        var parser = JPEGFrameParser()
        let prefix = Data("--frame\r\nContent-Type: image/jpeg\r\n\r\n".utf8)
        let first = Data([0xFF, 0xD8, 0x01, 0x02, 0xFF, 0xD9])
        let second = Data([0xFF, 0xD8, 0x03, 0x04, 0xFF, 0xD9])

        XCTAssertTrue(parser.append(prefix + first.prefix(3)).isEmpty)
        let frames = parser.append(first.suffix(3) + prefix + second)
        XCTAssertEqual(frames, [first, second])
    }

    func testMJPEGAcceptsOuterStreamAndIndividualJPEGPartResponses() throws {
        let url = URL(string: "https://robot.offerhack.io/api/cameras/front/stream")!
        let outer = HTTPURLResponse(
            url: url,
            statusCode: 200,
            httpVersion: "HTTP/2",
            headerFields: ["Content-Type": "multipart/x-mixed-replace; boundary=frame"]
        )!
        let part = HTTPURLResponse(
            url: url,
            statusCode: 200,
            httpVersion: "HTTP/2",
            headerFields: ["Content-Type": "image/jpeg"]
        )!

        XCTAssertNoThrow(
            try authenticatedRobotResponse(
                outer,
                contentTypes: ["multipart/x-mixed-replace", "image/jpeg"]
            )
        )
        XCTAssertNoThrow(
            try authenticatedRobotResponse(
                part,
                contentTypes: ["multipart/x-mixed-replace", "image/jpeg"]
            )
        )
    }

    func testLiveDashboardStateContractDecodes() throws {
        let json = #"""
        {
          "connected": true,
          "demo": false,
          "system_overall": "healthy",
          "sources": {
            "leader": { "connected": false, "motors": [] },
            "follower": {
              "connected": true,
              "stale": false,
              "joint_frame": "lekiwi-fusion-cad-v1",
              "motors": [
                {
                  "id": 1,
                  "name": "arm_shoulder_pan",
                  "label": "Shoulder pan",
                  "group": "arm",
                  "detected": true,
                  "severity": "healthy",
                  "position_deg": -7.2,
                  "joint_position_rad": -0.125663706,
                  "voltage_v": 12.4,
                  "temperature_c": 34
                }
              ]
            }
          },
          "control": {
            "available": true,
            "permitted": true,
            "permit_reason": "The follower owner loop is ready for dead-man browser control.",
            "enabled": false,
            "deadman_timeout_s": 0.35,
            "exclusive_base": true
          }
        }
        """#.data(using: .utf8)!

        let state = try JSONDecoder().decode(GatewayState.self, from: json)
        XCTAssertTrue(state.connected)
        XCTAssertEqual(state.sources.follower.motors.first?.temperature, 34)
        XCTAssertEqual(state.sources.follower.jointFrame, "lekiwi-fusion-cad-v1")
        XCTAssertEqual(state.sources.follower.motors.first?.jointPositionRadians, -0.125663706)
        XCTAssertEqual(state.control?.deadmanTimeoutSeconds, 0.35)
        XCTAssertTrue(state.control?.permitted == true)
    }

    func testCloudflareNativeCallbackExtractsJWTAndVerifiesState() throws {
        let state = "0123456789abcdef0123456789abcdef"
        let token = "header.payload.signature"
        let callback = URL(
            string: "com.raunaqnaidu.lekiwi://access/callback#token=\(token)&state=\(state)"
        )!

        XCTAssertEqual(try AccessCallback.token(from: callback, expectedState: state), token)
        XCTAssertThrowsError(try AccessCallback.token(from: callback, expectedState: "wrong-state"))
        XCTAssertEqual(
            RobotService.authenticationURL(state: state).absoluteString,
            "https://robot.offerhack.io/api/mobile/auth?state=\(state)"
        )
    }

    @MainActor
    func testProductionCloudflareSessionAuthenticatesStateAndLiveStreams() async throws {
        guard let token = ProcessInfo.processInfo.environment["LEKIWI_E2E_ACCESS_TOKEN"],
              !token.isEmpty else {
            throw XCTSkip("Set LEKIWI_E2E_ACCESS_TOKEN to run the production Access integration test.")
        }

        AccessTokenStore.clear()
        let store = RobotStore(restoreSession: false)
        store.completeAccessLogin(token: token, persist: false)

        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline,
              store.authenticationState != .authenticated,
              store.authenticationState != .expired {
            if case .failed = store.authenticationState { break }
            try await Task.sleep(for: .milliseconds(100))
        }

        XCTAssertEqual(store.authenticationState, .authenticated)
        try await Task.sleep(for: .seconds(3))
        XCTAssertEqual(
            store.authenticationState,
            .authenticated,
            "Cloudflare rejected: \(store.lastAuthenticationFailureSource ?? store.connectionMessage)."
        )
        XCTAssertNotNil(store.cameraImage, "The production front camera did not deliver a JPEG frame.")
        XCTAssertTrue(store.followerOnline, "The production follower telemetry was not live.")
        if store.state.control?.permitted == true {
            XCTAssertTrue(
                store.canArm,
                "Follower-ready control must not be blocked by the aggregate leader+follower connected flag."
            )
        }

        store.cameraImage = nil
        store.selectedCamera = "wrist"
        let wristDeadline = Date().addingTimeInterval(5)
        while Date() < wristDeadline, store.cameraImage == nil {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertNotNil(store.cameraImage, "The production wrist camera did not deliver a JPEG frame.")
        XCTAssertEqual(store.authenticationState, .authenticated)

        var stopRequest = URLRequest(url: RobotService.url(path: "api/control/stop"))
        stopRequest.httpMethod = "POST"
        stopRequest.setValue(token, forHTTPHeaderField: "cf-access-token")
        stopRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        stopRequest.setValue("dashboard-v1", forHTTPHeaderField: "X-LeKiwi-Control")
        stopRequest.httpBody = Data("{}".utf8)
        let (stopData, stopResponse) = try await URLSession.shared.data(for: stopRequest)
        _ = try authenticatedRobotResponse(stopResponse, contentType: "application/json")
        XCTAssertFalse(stopData.isEmpty, "The production stop control returned no response body.")

        store.disconnect()
        AccessTokenStore.clear()
    }
}
