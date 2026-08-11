import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: RobotStore

    var body: some View {
        Group {
            if store.canEnterApp {
                operatorTabs
            } else {
                LoginView()
            }
        }
        .animation(.easeOut(duration: 0.22), value: store.canEnterApp)
    }

    private var operatorTabs: some View {
        TabView {
            NavigationStack {
                OperateView()
                    .navigationTitle("Operate")
                    .navigationBarTitleDisplayMode(.inline)
            }
            .tabItem { Label("Operate", systemImage: "dot.scope") }

            NavigationStack {
                HealthView()
                    .navigationTitle("Robot health")
            }
            .tabItem { Label("Health", systemImage: "waveform.path.ecg") }

            NavigationStack {
                SettingsView()
                    .navigationTitle("Connection")
            }
            .tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}
