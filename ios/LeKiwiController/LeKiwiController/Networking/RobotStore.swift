import SwiftUI
import UIKit

enum BaseControlKey: String, CaseIterable, Hashable {
    case forward = "w"
    case backward = "s"
    case left = "a"
    case right = "d"
    case rotateLeft = "z"
    case rotateRight = "x"
}

enum JoystickCommandMapper {
    static func keys(translation: CGPoint, rotation: CGPoint, deadband: CGFloat = 0.16) -> Set<BaseControlKey> {
        var keys: Set<BaseControlKey> = []
        if translation.y < -deadband { keys.insert(.forward) }
        if translation.y > deadband { keys.insert(.backward) }
        if translation.x < -deadband { keys.insert(.left) }
        if translation.x > deadband { keys.insert(.right) }
        if rotation.x < -deadband { keys.insert(.rotateLeft) }
        if rotation.x > deadband { keys.insert(.rotateRight) }
        return keys
    }
}

enum ArmJoint: Int, CaseIterable, Identifiable {
    case shoulderPan = 1
    case shoulderLift = 2
    case elbowFlex = 3
    case wristFlex = 4
    case wristRoll = 5
    case gripper = 6

    var id: Int { rawValue }
    var serverKey: String {
        switch self {
        case .shoulderPan: "arm_shoulder_pan.pos"
        case .shoulderLift: "arm_shoulder_lift.pos"
        case .elbowFlex: "arm_elbow_flex.pos"
        case .wristFlex: "arm_wrist_flex.pos"
        case .wristRoll: "arm_wrist_roll.pos"
        case .gripper: "arm_gripper.pos"
        }
    }
    var label: String {
        switch self {
        case .shoulderPan: "Shoulder pan"
        case .shoulderLift: "Shoulder lift"
        case .elbowFlex: "Elbow flex"
        case .wristFlex: "Wrist flex"
        case .wristRoll: "Wrist roll"
        case .gripper: "Gripper"
        }
    }
    var symbol: String {
        switch self {
        case .shoulderPan: "arrow.triangle.2.circlepath"
        case .shoulderLift: "arrow.up.and.down"
        case .elbowFlex: "angle"
        case .wristFlex: "hand.point.up.left"
        case .wristRoll: "rotate.right"
        case .gripper: "arrow.left.and.right"
        }
    }
    var negativeLabel: String { self == .gripper ? "Close" : "−" }
    var positiveLabel: String { self == .gripper ? "Open" : "+" }
}

enum JointCommandMapper {
    static func direction(jog: CGPoint, deadband: CGFloat = 0.16) -> Int? {
        if jog.x < -deadband { return -1 }
        if jog.x > deadband { return 1 }
        return nil
    }
}

@MainActor
final class RobotStore: ObservableObject {
    enum ControlMode: String, CaseIterable, Identifiable {
        case base = "Omni base"
        case arm = "Follower arm"

        var id: String { rawValue }
        var symbol: String { self == .base ? "move.3d" : "arm.flex" }
    }

    enum SpeedLevel: String, CaseIterable, Identifiable {
        case slow = "Slow"
        case medium = "Medium"
        case fast = "Fast"

        var id: String { rawValue }
        var index: Int { self == .slow ? 0 : self == .medium ? 1 : 2 }
        var xy: Double { self == .slow ? 0.08 : self == .medium ? 0.16 : 0.25 }
        var theta: Double { self == .slow ? 25 : self == .medium ? 50 : 75 }
    }

    @Published var state = GatewayState.sample
    @Published var cameraImage: UIImage?
    @Published var selectedCamera = "front" {
        didSet {
            guard selectedCamera != oldValue else { return }
            cameraImage = nil
            restartCameraStream()
        }
    }
    @Published var selectedMotorID = 1 {
        didSet {
            guard selectedMotorID != oldValue else { return }
            let nextMode: ControlMode = selectedMotorID <= 6 ? .arm : .base
            if controlMode != nextMode { controlMode = nextMode }
            if isArmed || requestedDrive { releaseDrive(sendRemoteStop: isAuthenticated) }
        }
    }
    @Published var controlMode: ControlMode = .base {
        didSet {
            guard controlMode != oldValue else { return }
            if isArmed || requestedDrive { releaseDrive(sendRemoteStop: isAuthenticated) }
        }
    }
    @Published var connectionMessage = "Checking secure session…"
    @Published var isConnecting = false
    @Published private(set) var isArmed = false
    @Published private(set) var isEnablingControls = false
    @Published var translation = CGPoint.zero
    @Published var rotation = CGPoint.zero
    @Published var jointJog = CGPoint.zero
    @Published var speedLevel: SpeedLevel = .slow {
        didSet {
            guard speedLevel != oldValue, isArmed, !isDemoSession else { return }
            Task { _ = try? await postControl(path: "api/control/speed", payload: ["speed": speedLevel.index]) }
        }
    }
    @Published var authenticationState: AccessAuthenticationState = .checking
    @Published private(set) var isDemoSession = false
    @Published private(set) var lastAuthenticationFailureSource: String?

    private var stateTask: Task<Void, Never>?
    private var controlTask: Task<Void, Never>?
    private var motionPulseTask: Task<Void, Never>?
    private let cameraClient = MJPEGStreamClient()
    private let session: URLSession
    private var accessToken: String?
    private var requestedDrive = false
    private var driveRequestID = 0
    private var lastActiveKeys: Set<BaseControlKey> = []
    private var lastJointPulse: JointPulse?

    private struct JointPulse: Equatable {
        let joint: ArmJoint
        let direction: Int
    }

    init(restoreSession: Bool = true) {
        accessToken = AccessTokenStore.load()
        let configuration = URLSessionConfiguration.default
        configuration.httpCookieStorage = .shared
        configuration.httpShouldSetCookies = true
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        session = URLSession(configuration: configuration)

        cameraClient.onFrame = { [weak self] data in
            guard let image = UIImage(data: data) else { return }
            self?.cameraImage = image
        }
        cameraClient.onAuthenticationRequired = { [weak self] detail in
            guard let self else { return }
            self.authenticationExpired(source: "\(self.selectedCamera) camera stream (\(detail))")
        }
        cameraClient.onFailure = { [weak self] _ in
            guard let self, self.authenticationState == .authenticated else { return }
            self.cameraImage = nil
        }

        if restoreSession {
            Task { await restoreAccessSession() }
        }
    }

    var selectedMotor: MotorState? {
        state.sources.follower.motors.first { $0.id == selectedMotorID }
    }

    var selectedJoint: ArmJoint {
        ArmJoint(rawValue: selectedMotorID) ?? .shoulderPan
    }

    var followerOnline: Bool {
        state.sources.follower.connected && state.sources.follower.stale != true
    }

    var followerReady: Bool {
        if isDemoSession { return true }
        return followerOnline && state.control?.available == true && state.control?.permitted == true
    }

    var followerStatusTitle: String {
        if isDemoSession { return "Demo" }
        if followerReady { return "Robot ready" }
        if followerOnline { return "Robot paused" }
        return "Robot offline"
    }

    var followerStatusDetail: String {
        if isDemoSession { return "Illustrative controls only" }
        if !followerOnline { return "Follower telemetry is stale or unavailable." }
        return state.control?.permitReason ?? "Follower telemetry is online."
    }

    var isAuthenticated: Bool {
        authenticationState == .authenticated
    }

    var canEnterApp: Bool {
        isAuthenticated || isDemoSession
    }

    var canArm: Bool {
        if isDemoSession { return true }
        return isAuthenticated && followerReady
    }

    func selectControlMode(_ mode: ControlMode) {
        controlMode = mode
        if mode == .arm, selectedMotorID > 6 { selectedMotorID = ArmJoint.shoulderPan.id }
    }

    func selectJoint(_ joint: ArmJoint) {
        selectedMotorID = joint.id
        controlMode = .arm
    }

    func completeAccessLogin(token: String, persist: Bool = true) {
        authenticationState = .checking
        connectionMessage = "Verifying secure session…"
        Task {
            do {
                if persist {
                    try AccessTokenStore.save(token)
                }
                accessToken = token
                let liveState = try await fetchState()
                authenticationState = .authenticated
                isDemoSession = false
                update(with: liveState)
                connect()
            } catch {
                if persist {
                    AccessTokenStore.clear()
                }
                accessToken = nil
                authenticationState = .failed(error.localizedDescription)
                connectionMessage = "Sign-in could not be verified"
            }
        }
    }

    func useDemo() {
        stopNetwork()
        isDemoSession = true
        authenticationState = .signedOut
        state = .sample
        cameraImage = nil
        connectionMessage = "Demo telemetry · no commands sent"
    }

    func leaveDemo() {
        emergencyStop()
        isDemoSession = false
        state = .sample
        cameraImage = nil
        connectionMessage = "Sign in to connect"
    }

    func signOut() {
        Task {
            if isAuthenticated {
                _ = try? await postControl(path: "api/control/stop", payload: [:], applyState: false)
                _ = try? await postControl(path: "api/control/enable", payload: ["enabled": false], applyState: false)
            }
            releaseDrive(sendRemoteStop: false)
            stopNetwork()
            await AccessCookieManager.clear()
            accessToken = nil
            authenticationState = .signedOut
            isDemoSession = false
            cameraImage = nil
            connectionMessage = "Signed out"
        }
    }

    func connect() {
        guard isAuthenticated else { return }
        releaseDrive(sendRemoteStop: isArmed || requestedDrive || !lastActiveKeys.isEmpty)
        stopNetwork()
        isConnecting = true
        connectionMessage = "Connecting to robot…"

        stateTask = Task { [weak self] in
            await self?.runStateStream()
        }
        controlTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if self.isArmed {
                    await self.pulseCurrentControls()
                }
                try? await Task.sleep(for: .milliseconds(160))
            }
        }
        restartCameraStream()
    }

    func disconnect(keepMessage: Bool = false) {
        emergencyStop()
        stopNetwork()
        if !keepMessage {
            connectionMessage = "Disconnected"
        }
    }

    func setArmed(_ armed: Bool) {
        if !armed {
            releaseDrive(sendRemoteStop: true)
            return
        }

        guard !isArmed, !isEnablingControls else { return }

        guard canArm else {
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
            connectionMessage = state.control?.permitReason ?? "Robot controls are not ready"
            return
        }

        requestedDrive = true
        isEnablingControls = true
        driveRequestID += 1
        let requestID = driveRequestID

        if isDemoSession {
            isArmed = true
            isEnablingControls = false
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            return
        }

        Task {
            do {
                try await postControl(path: "api/control/enable", payload: ["enabled": true])
                if controlMode == .base {
                    try await postControl(path: "api/control/arm", payload: ["enabled": false])
                    try await postControl(path: "api/control/speed", payload: ["speed": speedLevel.index])
                } else {
                    try await postControl(path: "api/control/arm", payload: ["enabled": true])
                }
                guard requestedDrive, driveRequestID == requestID else {
                    _ = try? await postControl(path: "api/control/stop", payload: [:], applyState: false)
                    return
                }
                isArmed = true
                isEnablingControls = false
                UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            } catch {
                handleControlFailure(error)
            }
        }
    }

    func pulseBase(_ key: BaseControlKey) {
        guard isArmed, controlMode == .base else {
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
            return
        }

        motionPulseTask?.cancel()
        translation = .zero
        rotation = .zero
        switch key {
        case .forward: translation.y = -1
        case .backward: translation.y = 1
        case .left: translation.x = -1
        case .right: translation.x = 1
        case .rotateLeft: rotation.x = -1
        case .rotateRight: rotation.x = 1
        }
        scheduleMotionStop()
    }

    func pulseJoint(direction: Int) {
        guard isArmed, controlMode == .arm, direction == -1 || direction == 1 else {
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
            return
        }

        motionPulseTask?.cancel()
        jointJog = CGPoint(x: direction, y: 0)
        scheduleMotionStop()
    }

    func emergencyStop() {
        releaseDrive(sendRemoteStop: isAuthenticated)
    }

    func sceneDidBecomeActive() {
        if isAuthenticated {
            connect()
        }
    }

    func sceneDidEnterBackground() {
        emergencyStop()
        stopNetwork()
    }

    private func restoreAccessSession() async {
        accessToken = AccessTokenStore.load()
        await AccessCookieManager.synchronizeToFoundation()
        do {
            let liveState = try await fetchState()
            authenticationState = .authenticated
            update(with: liveState)
            connect()
        } catch RobotNetworkError.authenticationRequired {
            authenticationState = .signedOut
            connectionMessage = "Sign in to connect"
        } catch {
            authenticationState = .signedOut
            connectionMessage = "Sign in to connect"
        }
    }

    private func runStateStream() async {
        while !Task.isCancelled, isAuthenticated {
            do {
                let initial = try await fetchState()
                update(with: initial)

                var request = robotRequest(path: "api/stream")
                request.timeoutInterval = 60
                let (bytes, response) = try await session.bytes(for: request)
                _ = try authenticatedRobotResponse(response, contentType: "text/event-stream")

                var eventName = ""
                var dataLines: [String] = []
                for try await line in bytes.lines {
                    if Task.isCancelled { return }
                    if line.isEmpty {
                        if eventName == "state", !dataLines.isEmpty {
                            let data = Data(dataLines.joined(separator: "\n").utf8)
                            let next = try JSONDecoder().decode(GatewayState.self, from: data)
                            update(with: next)
                        }
                        eventName = ""
                        dataLines.removeAll(keepingCapacity: true)
                    } else if line.hasPrefix("event:") {
                        eventName = line.dropFirst("event:".count).trimmingCharacters(in: .whitespaces)
                    } else if line.hasPrefix("data:") {
                        dataLines.append(line.dropFirst("data:".count).trimmingCharacters(in: .whitespaces))
                    }
                }
            } catch RobotNetworkError.authenticationRequired {
                authenticationExpired(source: "telemetry stream")
                return
            } catch {
                isConnecting = false
                state.connected = false
                connectionMessage = "Robot service interrupted · reconnecting"
                releaseDrive(sendRemoteStop: false)
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private func fetchState() async throws -> GatewayState {
        let (data, response) = try await session.data(for: robotRequest(path: "api/state"))
        _ = try authenticatedRobotResponse(response, contentType: "application/json")
        return try JSONDecoder().decode(GatewayState.self, from: data)
    }

    private func update(with next: GatewayState) {
        state = next
        isConnecting = false
        connectionMessage = followerOnline ? "Follower online" : "Service online · follower offline"
        if next.control?.permitted == false, isArmed {
            releaseDrive(sendRemoteStop: false)
            connectionMessage = next.control?.permitReason ?? "Robot controls paused"
        }
    }

    private func restartCameraStream() {
        cameraClient.stop()
        guard isAuthenticated else { return }
        var headers: [String: String] = [:]
        if let accessToken {
            headers["cf-access-token"] = accessToken
        }
        cameraClient.start(
            url: RobotService.url(path: "api/cameras/\(selectedCamera)/stream"),
            headers: headers
        )
    }

    private func stopNetwork() {
        stateTask?.cancel()
        controlTask?.cancel()
        stateTask = nil
        controlTask = nil
        cameraClient.stop()
        isConnecting = false
    }

    private func releaseDrive(sendRemoteStop: Bool) {
        let wasActive = requestedDrive || isArmed || !lastActiveKeys.isEmpty
        motionPulseTask?.cancel()
        motionPulseTask = nil
        requestedDrive = false
        driveRequestID += 1
        isArmed = false
        isEnablingControls = false
        translation = .zero
        rotation = .zero
        jointJog = .zero
        lastActiveKeys = []
        lastJointPulse = nil
        if wasActive {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        }
        guard sendRemoteStop else { return }
        Task {
            _ = try? await postControl(path: "api/control/stop", payload: [:], applyState: false)
            _ = try? await postControl(path: "api/control/enable", payload: ["enabled": false], applyState: false)
        }
    }

    private func pulseCurrentControls() async {
        if controlMode == .arm {
            await pulseCurrentJoint()
            return
        }

        let active = JoystickCommandMapper.keys(translation: translation, rotation: rotation)
        let released = lastActiveKeys.subtracting(active)
        lastActiveKeys = active

        let operations = released.map { ($0, false) } + active.map { ($0, true) }
        guard !operations.isEmpty else { return }

        let succeeded = await withTaskGroup(of: Bool.self, returning: Bool.self) { group in
            for (key, isActive) in operations {
                group.addTask { [weak self] in
                    guard let self else { return false }
                    do {
                        try await self.postControl(
                            path: "api/control/base",
                            payload: ["key": key.rawValue, "active": isActive],
                            applyState: false
                        )
                        return true
                    } catch {
                        return false
                    }
                }
            }
            var allSucceeded = true
            for await result in group {
                allSucceeded = allSucceeded && result
            }
            return allSucceeded
        }

        if !succeeded {
            handleControlFailure(RobotNetworkError.server("Control link interrupted. Enable movement again to continue."))
        }
    }

    private func pulseCurrentJoint() async {
        let nextPulse = JointCommandMapper.direction(jog: jointJog).map {
            JointPulse(joint: selectedJoint, direction: $0)
        }
        var operations: [(JointPulse, Bool)] = []
        if let previous = lastJointPulse, previous != nextPulse {
            operations.append((previous, false))
        }
        if let nextPulse {
            operations.append((nextPulse, true))
        }
        lastJointPulse = nextPulse
        guard !operations.isEmpty else { return }

        for (pulse, active) in operations {
            do {
                try await postControl(
                    path: "api/control/joint",
                    payload: [
                        "joint": pulse.joint.serverKey,
                        "direction": pulse.direction,
                        "active": active,
                    ],
                    applyState: false
                )
            } catch {
                handleControlFailure(RobotNetworkError.server("Joint control was interrupted. Enable movement again to continue."))
                return
            }
        }
    }

    private func scheduleMotionStop() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        motionPulseTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(420))
            guard !Task.isCancelled, let self else { return }
            self.translation = .zero
            self.rotation = .zero
            self.jointJog = .zero
            self.motionPulseTask = nil
        }
    }

    @discardableResult
    private func postControl(path: String, payload: [String: Any], applyState: Bool = true) async throws -> GatewayState? {
        var request = robotRequest(path: path)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("dashboard-v1", forHTTPHeaderField: "X-LeKiwi-Control")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        request.timeoutInterval = 2.5

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.url?.host == RobotService.host else {
            throw RobotNetworkError.authenticationRequired
        }
        guard http.value(forHTTPHeaderField: "Content-Type")?.lowercased().contains("application/json") == true else {
            throw RobotNetworkError.authenticationRequired
        }

        let envelope = try JSONDecoder().decode(ControlResponse.self, from: data)
        guard http.statusCode == 200, envelope.ok else {
            throw RobotNetworkError.server(envelope.error ?? "Robot rejected the control command.")
        }
        if applyState, let next = envelope.state {
            update(with: next)
        }
        return envelope.state
    }

    private func robotRequest(path: String) -> URLRequest {
        var request = URLRequest(url: RobotService.url(path: path))
        if let accessToken {
            request.setValue(accessToken, forHTTPHeaderField: "cf-access-token")
        }
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 3
        return request
    }

    private func handleControlFailure(_ error: Error) {
        releaseDrive(sendRemoteStop: false)
        connectionMessage = error.localizedDescription
        UINotificationFeedbackGenerator().notificationOccurred(.error)
    }

    private func authenticationExpired(source: String) {
        lastAuthenticationFailureSource = source
        releaseDrive(sendRemoteStop: false)
        stopNetwork()
        AccessTokenStore.clear()
        accessToken = nil
        authenticationState = .expired
        cameraImage = nil
        connectionMessage = "Cloudflare rejected the \(source)"
    }
}
