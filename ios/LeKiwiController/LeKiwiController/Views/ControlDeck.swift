import SwiftUI

struct ControlDeck: View {
    @EnvironmentObject private var store: RobotStore
    var compact: Bool

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(spacing: compact ? 8 : 10) {
                controlModePicker

                if store.controlMode == .base {
                    baseControls
                } else {
                    armControls
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, compact ? 8 : 10)
            .padding(.bottom, compact ? 6 : 8)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemBackground))
        .overlay(alignment: .top) { Divider() }
        .accessibilityElement(children: .contain)
    }

    private var controlModePicker: some View {
        Picker("Control target", selection: Binding(
            get: { store.controlMode },
            set: { store.selectControlMode($0) }
        )) {
            ForEach(RobotStore.ControlMode.allCases) { mode in
                Label(mode.rawValue, systemImage: mode.symbol).tag(mode)
            }
        }
        .pickerStyle(.segmented)
        .accessibilityHint("Choose the omniwheel base or one follower-arm joint")
    }

    private var baseControls: some View {
        VStack(spacing: compact ? 8 : 10) {
            readinessRow(target: "base")

            Picker("Drive speed", selection: $store.speedLevel) {
                ForEach(RobotStore.SpeedLevel.allCases) { level in
                    Text(level.rawValue).tag(level)
                }
            }
            .pickerStyle(.segmented)

            HStack {
                Text("Tap a direction to move briefly")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(store.speedLevel.rawValue)
                    .font(.caption.weight(.semibold))
            }

            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                motionButton("Turn left", symbol: "arrow.counterclockwise", key: .rotateLeft)
                motionButton("Forward", symbol: "arrow.up", key: .forward)
                motionButton("Turn right", symbol: "arrow.clockwise", key: .rotateRight)
                motionButton("Left", symbol: "arrow.left", key: .left)
                stopButton
                motionButton("Right", symbol: "arrow.right", key: .right)
                Color.clear.frame(height: 50)
                motionButton("Back", symbol: "arrow.down", key: .backward)
                Color.clear.frame(height: 50)
            }
        }
    }

    private var armControls: some View {
        VStack(spacing: compact ? 8 : 10) {
            readinessRow(target: store.selectedJoint.label.lowercased())

            Menu {
                ForEach(ArmJoint.allCases) { joint in
                    Button {
                        store.selectJoint(joint)
                    } label: {
                        Label("\(joint.label) · motor ID \(joint.id)", systemImage: store.selectedJoint == joint ? "checkmark" : joint.symbol)
                    }
                }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: store.selectedJoint.symbol)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Follower joint")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text("\(store.selectedJoint.label) · ID \(store.selectedJoint.id)")
                            .font(.subheadline.weight(.semibold))
                    }
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)

            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible())], spacing: 0) {
                jointButton(direction: -1, label: store.selectedJoint.negativeLabel)
                jointButton(direction: 1, label: store.selectedJoint.positiveLabel)
            }
            .frame(maxWidth: .infinity)

            HStack(spacing: 12) {
                if let position = store.selectedMotor?.positionDegrees {
                    Label(
                        store.selectedJoint == .gripper ? String(format: "%.1f%%", position) : String(format: "%.1f°", position),
                        systemImage: "ruler"
                    )
                }
                if let motor = store.selectedMotor {
                    Label(motor.temperature.map { "\(Int($0))°C" } ?? "—", systemImage: "thermometer.medium")
                    Label(motor.voltage.map { String(format: "%.1f V", $0) } ?? "—", systemImage: "bolt.fill")
                }
                Spacer(minLength: 0)
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }

    private func readinessRow(target: String) -> some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(store.isArmed ? "Movement enabled" : store.canArm ? "Movement is off" : "Controls paused")
                    .font(.subheadline.weight(.semibold))
                Text(store.isArmed ? "Each tap sends one short \(target) movement." : store.canArm ? "Enable it, then use the buttons below." : store.followerStatusDetail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Spacer(minLength: 4)
            Button {
                store.setArmed(!store.isArmed)
            } label: {
                Label(
                    store.isArmed ? "Stop" : store.isEnablingControls ? "Enabling" : "Enable",
                    systemImage: store.isArmed ? "stop.fill" : "power"
                )
                .font(.subheadline.weight(.semibold))
                .frame(minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .tint(store.isArmed ? AppPalette.critical : AppPalette.indigo)
            .disabled((!store.canArm && !store.isArmed) || store.isEnablingControls)
            .accessibilityHint(store.isArmed ? "Stops motion and disables every movement button" : "Turns on the movement buttons")
        }
    }

    private func motionButton(_ label: String, symbol: String, key: BaseControlKey) -> some View {
        Button { store.pulseBase(key) } label: {
            VStack(spacing: 2) {
                Image(systemName: symbol)
                    .font(.headline)
                Text(label)
                    .font(.caption2.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
            .frame(maxWidth: .infinity, minHeight: compact ? 44 : 50)
        }
        .buttonStyle(.bordered)
        .disabled(!store.isArmed)
    }

    private var stopButton: some View {
        Button { store.emergencyStop() } label: {
            VStack(spacing: 2) {
                Image(systemName: "stop.fill")
                    .font(.headline)
                Text("Stop")
                    .font(.caption2.weight(.semibold))
            }
            .frame(maxWidth: .infinity, minHeight: compact ? 44 : 50)
        }
        .buttonStyle(.borderedProminent)
        .tint(AppPalette.critical)
        .disabled(!store.isArmed)
        .accessibilityHint("Stops motion and disables the controls")
    }

    private func jointButton(direction: Int, label: String) -> some View {
        Button { store.pulseJoint(direction: direction) } label: {
            Text(label)
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: compact ? 50 : 58)
        }
        .buttonStyle(.bordered)
        .disabled(!store.isArmed)
        .accessibilityLabel("Move \(store.selectedJoint.label) \(label) one step")
    }
}
