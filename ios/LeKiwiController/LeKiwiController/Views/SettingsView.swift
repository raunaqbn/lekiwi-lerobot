import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: RobotStore
    @State private var confirmingSignOut = false

    var body: some View {
        Form {
            Section {
                LabeledContent("Status") {
                    Label(store.connectionMessage, systemImage: store.state.connected ? "checkmark.circle.fill" : "wifi.slash")
                        .foregroundStyle(store.state.connected ? AppPalette.healthy : .secondary)
                }
                LabeledContent("Service", value: "robot.offerhack.io")
                if let timeout = store.state.control?.deadmanTimeoutSeconds {
                    LabeledContent("Motion timeout", value: "\(Int(timeout * 1_000)) ms")
                } else if let deadman = store.state.control?.deadmanMs {
                    LabeledContent("Motion timeout", value: "\(deadman) ms")
                }
            }

            if store.isAuthenticated {
                Section("Cloudflare Access") {
                    Label("Secure session active", systemImage: "lock.shield.fill")
                        .foregroundStyle(AppPalette.healthy)
                    Button("Reconnect live feeds") {
                        store.connect()
                    }
                    Link(destination: RobotService.baseURL) {
                        Label("Open web dashboard", systemImage: "safari")
                    }
                    Button("Sign out", role: .destructive) {
                        confirmingSignOut = true
                    }
                }
            } else if store.isDemoSession {
                Section("Preview") {
                    Label("Illustrative telemetry only", systemImage: "eye.fill")
                        .foregroundStyle(AppPalette.indigo)
                    Button("Leave preview and sign in") {
                        store.leaveDemo()
                    }
                }
            }

            if let reason = store.state.control?.permitReason, store.isAuthenticated {
                Section("Control readiness") {
                    Label(reason, systemImage: store.canArm ? "checkmark.shield.fill" : "pause.circle.fill")
                        .foregroundStyle(store.canArm ? AppPalette.healthy : AppPalette.warning)
                }
            }

            Section("Safety") {
                Label("Each direction tap is brief. Stop, app backgrounding, or a missed dead-man pulse disables motion.", systemImage: "hand.raised.fill")
                Label("Use the robot’s physical power cutoff for a true emergency stop.", systemImage: "power")
            }
        }
        .confirmationDialog(
            "Sign out of this robot?",
            isPresented: $confirmingSignOut,
            titleVisibility: .visible
        ) {
            Button("Sign out", role: .destructive) {
                store.signOut()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Motion will stop and the app’s Cloudflare Access session will be removed.")
        }
    }
}
