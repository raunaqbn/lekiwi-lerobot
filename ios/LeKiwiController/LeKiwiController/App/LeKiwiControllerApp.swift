import SwiftUI

// THESIS: Camera and digital twin form one operating field; this refuses the tab-per-feed controller.
// OWN-WORLD: Cool mist, structural white, ink navy, indigo routing, and named health colors in native iOS materials.
// STORY: Connect, see the physical path and robot state together, hold deliberately, drive, and release to stop.
// FIRST VIEWPORT: Camera owns the upper field, the live twin rises from its lower edge, and controls occupy the safe shelf.
// FORM: Spatial Cockpit, grounded structure six, fused-media staging, surface seed 312d7d7e.
@main
struct LeKiwiControllerApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var store = RobotStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .tint(AppPalette.indigo)
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active {
                        store.sceneDidBecomeActive()
                    } else {
                        store.sceneDidEnterBackground()
                    }
                }
        }
    }
}

enum AppPalette {
    static let indigo = Color(red: 0.357, green: 0.361, blue: 0.886)
    static let navy = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.91, green: 0.93, blue: 0.97, alpha: 1)
            : UIColor(red: 0.09, green: 0.125, blue: 0.2, alpha: 1)
    })
    static let mist = Color(uiColor: .systemGroupedBackground)
    static let healthy = Color(red: 0.086, green: 0.525, blue: 0.361)
    static let warning = Color(red: 0.714, green: 0.42, blue: 0.031)
    static let critical = Color(red: 0.784, green: 0.239, blue: 0.302)
}
