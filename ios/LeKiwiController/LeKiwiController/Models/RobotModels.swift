import Foundation

struct GatewayState: Codable {
    var apiVersion: Int?
    var connected: Bool
    var demo: Bool?
    var lastUpdate: String?
    var systemOverall: String?
    var systemCounts: MotorCounts?
    var battery: BatteryState?
    var sources: RobotSources
    var control: ControlState?
    var gatewayError: String?

    enum CodingKeys: String, CodingKey {
        case connected, demo, battery, sources, control
        case apiVersion = "api_version"
        case lastUpdate = "last_update"
        case systemOverall = "system_overall"
        case systemCounts = "system_counts"
        case gatewayError = "gateway_error"
    }
}

struct RobotSources: Codable {
    var leader: RobotSource?
    var follower: RobotSource
}

struct RobotSource: Codable {
    var source: String?
    var sourceLabel: String?
    var connected: Bool
    var stale: Bool?
    var lastUpdate: String?
    var jointFrame: String?
    var overall: String?
    var error: String?
    var counts: MotorCounts?
    var power: PowerState?
    var battery: BatteryState?
    var motors: [MotorState]
    var findings: [Finding]?
    var profile: RobotProfile?

    enum CodingKeys: String, CodingKey {
        case source, connected, stale, overall, error, counts, power, battery, motors, findings, profile
        case sourceLabel = "source_label"
        case lastUpdate = "last_update"
        case jointFrame = "joint_frame"
    }
}

struct MotorCounts: Codable {
    var expected: Int
    var detected: Int
    var healthy: Int
    var warning: Int
    var critical: Int
    var unpowered: Int?
}

struct BatteryState: Codable {
    var available: Bool
    var voltage: Double?
    var percentMin: Int?
    var percentMax: Int?
    var confidence: String?
    var remainingWhMin: Double?
    var remainingWhMax: Double?

    enum CodingKeys: String, CodingKey {
        case available, confidence
        case voltage = "voltage_v"
        case percentMin = "percent_min"
        case percentMax = "percent_max"
        case remainingWhMin = "remaining_wh_min"
        case remainingWhMax = "remaining_wh_max"
    }
}

struct PowerState: Codable {
    var usbController: String?
    var servoRail: String?
    var confidence: String?
    var detail: String?

    enum CodingKeys: String, CodingKey {
        case confidence, detail
        case usbController = "usb_controller"
        case servoRail = "servo_rail"
    }
}

struct RobotProfile: Codable {
    var key: String?
    var label: String?
}

struct Finding: Codable, Identifiable {
    var id: String { "\(severity ?? "unknown")-\(title ?? "finding")" }
    var severity: String?
    var title: String?
    var detail: String?
}

struct MotorState: Codable, Identifiable, Hashable {
    var id: Int
    var name: String
    var label: String
    var group: String
    var detected: Bool
    var model: String?
    var positionDegrees: Double?
    var jointPositionRadians: Double?
    var velocityDegreesPerSecond: Double?
    var voltage: Double?
    var temperature: Double?
    var currentRaw: Double?
    var torqueEnabled: Bool?
    var severity: String
    var findings: [String]?

    enum CodingKeys: String, CodingKey {
        case id, name, label, group, detected, model, severity, findings
        case positionDegrees = "position_deg"
        case jointPositionRadians = "joint_position_rad"
        case velocityDegreesPerSecond = "velocity_deg_s"
        case voltage = "voltage_v"
        case temperature = "temperature_c"
        case currentRaw = "current_raw"
        case torqueEnabled = "torque_enabled"
    }
}

struct ControlState: Codable {
    var available: Bool?
    var controllerActive: Bool?
    var armed: Bool?
    var commandAgeMs: Int?
    var deadmanMs: Int?
    var maxXY: Double?
    var maxTheta: Double?
    var permitted: Bool?
    var permitReason: String?
    var enabled: Bool?
    var armTakeover: Bool?
    var stopLatched: Bool?
    var speedIndex: Int?
    var speedLabel: String?
    var xySpeed: Double?
    var thetaSpeed: Double?
    var deadmanTimeoutSeconds: Double?
    var exclusiveBase: Bool?

    enum CodingKeys: String, CodingKey {
        case available, armed, permitted, enabled
        case controllerActive = "controller_active"
        case commandAgeMs = "command_age_ms"
        case deadmanMs = "deadman_ms"
        case maxXY = "max_xy_m_s"
        case maxTheta = "max_theta_deg_s"
        case permitReason = "permit_reason"
        case armTakeover = "arm_takeover"
        case stopLatched = "stop_latched"
        case speedIndex = "speed_index"
        case speedLabel = "speed_label"
        case xySpeed = "xy_speed_m_s"
        case thetaSpeed = "theta_speed_deg_s"
        case deadmanTimeoutSeconds = "deadman_timeout_s"
        case exclusiveBase = "exclusive_base"
    }
}

struct ControlResponse: Codable {
    var ok: Bool
    var error: String?
    var state: GatewayState?
}

extension GatewayState {
    static let sample: GatewayState = {
        let names = [
            ("arm_shoulder_pan", "Shoulder pan", "arm"),
            ("arm_shoulder_lift", "Shoulder lift", "arm"),
            ("arm_elbow_flex", "Elbow flex", "arm"),
            ("arm_wrist_flex", "Wrist flex", "arm"),
            ("arm_wrist_roll", "Wrist roll", "arm"),
            ("arm_gripper", "Gripper", "arm"),
            ("base_left_wheel", "Left wheel", "base"),
            ("base_back_wheel", "Back wheel", "base"),
            ("base_right_wheel", "Right wheel", "base")
        ]
        let positions = [-7.0, 39.5, 27.3, 4.9, -106.7, 29.5, 0.0, 0.0, 0.0]
        let cadRadians = [-0.123, -2.260, 1.095, 1.486, -1.862, -0.681, 0.0, 0.0, 0.0]
        let motors = names.enumerated().map { index, item in
            MotorState(
                id: index + 1,
                name: item.0,
                label: item.1,
                group: item.2,
                detected: index != 7,
                model: "STS3215",
                positionDegrees: positions[index],
                jointPositionRadians: cadRadians[index],
                velocityDegreesPerSecond: index > 5 ? Double(index - 5) * 9 : 0,
                voltage: 11.8,
                temperature: Double(31 + index),
                currentRaw: Double(20 + index * 3),
                torqueEnabled: true,
                severity: index == 7 ? "critical" : index == 4 ? "warning" : "healthy",
                findings: index == 7 ? ["No response on the selected baud rate"] : nil
            )
        }
        let counts = MotorCounts(expected: 9, detected: 8, healthy: 7, warning: 1, critical: 1, unpowered: 0)
        let battery = BatteryState(available: true, voltage: 11.8, percentMin: 45, percentMax: 85, confidence: "low", remainingWhMin: 26, remainingWhMax: 49.1)
        let follower = RobotSource(
            source: "follower",
            sourceLabel: "Follower robot",
            connected: true,
            stale: false,
            lastUpdate: nil,
            jointFrame: "lekiwi-fusion-cad-v1",
            overall: "warning",
            error: nil,
            counts: counts,
            power: PowerState(usbController: "online", servoRail: "powered", confidence: "confirmed", detail: "Eight servos returned powered status packets."),
            battery: battery,
            motors: motors,
            findings: [Finding(severity: "critical", title: "Back wheel", detail: "No response on the selected baud rate")],
            profile: RobotProfile(key: "lekiwi_follower_12v", label: "LeKiwi follower · 9 motors · 12 V")
        )
        return GatewayState(
            apiVersion: 1,
            connected: true,
            demo: true,
            lastUpdate: nil,
            systemOverall: "warning",
            systemCounts: counts,
            battery: battery,
            sources: RobotSources(leader: nil, follower: follower),
            control: ControlState(
                available: true,
                controllerActive: false,
                armed: false,
                commandAgeMs: nil,
                deadmanMs: nil,
                maxXY: nil,
                maxTheta: nil,
                permitted: true,
                permitReason: "Demo controls never send commands.",
                enabled: false,
                armTakeover: false,
                stopLatched: false,
                speedIndex: 0,
                speedLabel: "slow",
                xySpeed: 0.08,
                thetaSpeed: 25,
                deadmanTimeoutSeconds: 0.35,
                exclusiveBase: true
            ),
            gatewayError: nil
        )
    }()
}
