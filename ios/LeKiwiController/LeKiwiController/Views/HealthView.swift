import SwiftUI

struct HealthView: View {
    @EnvironmentObject private var store: RobotStore

    var body: some View {
        List {
            Section {
                HStack(spacing: 14) {
                    Image(systemName: verdictSymbol)
                        .font(.title2)
                        .foregroundStyle(verdictColor)
                        .frame(width: 44, height: 44)
                        .background(verdictColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(verdictTitle).font(.headline)
                        Text(store.connectionMessage).font(.subheadline).foregroundStyle(.secondary)
                    }
                }
            }

            Section("Follower power") {
                LabeledContent("USB controller", value: store.state.sources.follower.power?.usbController?.capitalized ?? "Unknown")
                LabeledContent("Servo rail", value: store.state.sources.follower.power?.servoRail?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Unknown")
                if let battery = store.state.battery, battery.available {
                    LabeledContent("Battery", value: "\(battery.percentMin ?? 0)–\(battery.percentMax ?? 0)%")
                    LabeledContent("Rail voltage", value: battery.voltage.map { String(format: "%.1f V", $0) } ?? "—")
                }
                if let detail = store.state.sources.follower.power?.detail {
                    Text(detail).font(.footnote).foregroundStyle(.secondary)
                }
            }

            if let findings = store.state.sources.follower.findings, !findings.isEmpty {
                Section("Needs attention") {
                    ForEach(findings) { finding in
                        Label {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(finding.title ?? "Finding").font(.body.weight(.semibold))
                                Text(finding.detail ?? "Check the motor connection.").font(.footnote).foregroundStyle(.secondary)
                            }
                        } icon: {
                            Image(systemName: finding.severity == "critical" ? "exclamationmark.octagon.fill" : "exclamationmark.triangle.fill")
                                .foregroundStyle(finding.severity == "critical" ? AppPalette.critical : AppPalette.warning)
                        }
                    }
                }
            }

            Section("Motor readings") {
                ForEach(store.state.sources.follower.motors) { motor in
                    Button {
                        store.selectedMotorID = motor.id
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: symbol(for: motor.severity))
                                .foregroundStyle(color(for: motor.severity))
                                .frame(width: 20)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(motor.label).foregroundStyle(.primary)
                                Text("ID \(motor.id) · \(motor.group.capitalized)").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(motor.temperature.map { "\(Int($0))°C" } ?? "—").monospacedDigit()
                                Text(motor.voltage.map { String(format: "%.1f V", $0) } ?? "—").font(.caption).foregroundStyle(.secondary).monospacedDigit()
                            }
                        }
                    }
                }
            }

            if let profile = store.state.sources.follower.profile?.label {
                Section("Bus") { Text(profile).font(.footnote).foregroundStyle(.secondary) }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { store.connect() }
    }

    private var verdictTitle: String {
        if store.state.demo == true { return "Illustrative robot telemetry" }
        if !store.followerOnline { return "Follower robot is offline" }
        if store.state.sources.follower.overall == "critical" { return "A follower motor needs attention" }
        if store.state.sources.follower.overall == "warning" { return "Follower is online with warnings" }
        return store.followerReady ? "Follower is healthy and ready" : "Follower is healthy; controls are paused"
    }

    private var verdictSymbol: String {
        !store.followerOnline ? "wifi.slash" : store.state.sources.follower.overall == "critical" ? "exclamationmark.octagon.fill" : "checkmark.shield.fill"
    }

    private var verdictColor: Color {
        !store.followerOnline ? .secondary : store.state.sources.follower.overall == "critical" ? AppPalette.critical : store.state.sources.follower.overall == "warning" ? AppPalette.warning : store.followerReady ? AppPalette.healthy : AppPalette.warning
    }

    private func symbol(for severity: String) -> String {
        switch severity {
        case "warning": return "exclamationmark.triangle.fill"
        case "critical": return "xmark.octagon.fill"
        case "unpowered": return "bolt.slash.fill"
        default: return "checkmark.circle"
        }
    }

    private func color(for severity: String) -> Color {
        severity == "warning" ? AppPalette.warning : severity == "critical" ? AppPalette.critical : .secondary
    }
}
