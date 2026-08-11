import SwiftUI

struct OperateView: View {
    @EnvironmentObject private var store: RobotStore
    @State private var showsTwin = false

    var body: some View {
        GeometryReader { proxy in
            let landscape = proxy.size.width > proxy.size.height
            let compact = proxy.size.height < 700

            if landscape {
                HStack(spacing: 0) {
                    CameraField(showTwin: { showsTwin = true })
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    ControlDeck(compact: true)
                        .frame(width: min(430, proxy.size.width * 0.48))
                }
            } else {
                VStack(spacing: 0) {
                    CameraField(showTwin: { showsTwin = true })
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .layoutPriority(1)
                    ControlDeck(compact: compact)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .background(AppPalette.mist.ignoresSafeArea())
        .sheet(isPresented: $showsTwin) {
            NavigationStack {
                TwinTelemetryView()
                    .navigationTitle("3D model")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { showsTwin = false }
                        }
                    }
            }
            .presentationDetents([.large])
        }
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                HStack(spacing: 6) {
                    Image(systemName: "point.3.connected.trianglepath.dotted")
                        .foregroundStyle(AppPalette.indigo)
                    Text("LeKiwi").fontWeight(.semibold)
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                ConnectionChip()
            }
        }
    }
}

private struct ConnectionChip: View {
    @EnvironmentObject private var store: RobotStore

    var body: some View {
        let counts = store.state.sources.follower.counts
        HStack(spacing: 5) {
            Image(systemName: connectionSymbol)
                .foregroundStyle(connectionColor)
            Text(store.followerStatusTitle)
                .font(.caption.weight(.semibold))
            if let counts {
                Text("\(counts.detected)/\(counts.expected)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .lineLimit(1)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(store.followerStatusTitle). \(store.followerStatusDetail)")
    }

    private var connectionSymbol: String {
        if store.isDemoSession { return "play.rectangle.fill" }
        if store.followerReady { return "checkmark.circle.fill" }
        if store.followerOnline { return "pause.circle.fill" }
        return "exclamationmark.triangle.fill"
    }

    private var connectionColor: Color {
        if store.isDemoSession { return AppPalette.indigo }
        if store.followerReady { return .secondary }
        if store.followerOnline { return AppPalette.warning }
        return AppPalette.critical
    }
}

private struct CameraField: View {
    @EnvironmentObject private var store: RobotStore
    let showTwin: () -> Void

    var body: some View {
        ZStack(alignment: .top) {
            if let image = store.cameraImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else if store.isDemoSession {
                DemoCameraPlate()
            } else {
                CameraWaitingPlate(camera: store.selectedCamera)
            }

            HStack(spacing: 8) {
                Picker("Camera", selection: $store.selectedCamera) {
                    Text("Front").tag("front")
                    Text("Wrist").tag("wrist")
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 180)
                .onChange(of: store.selectedCamera) { _, _ in store.cameraImage = nil }

                Spacer(minLength: 0)

                Button(action: showTwin) {
                    Label("3D", systemImage: "cube.transparent")
                        .font(.subheadline.weight(.semibold))
                        .padding(.horizontal, 12)
                        .frame(minHeight: 44)
                        .background(.regularMaterial, in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Open 3D robot model")
            }
            .padding(10)
        }
        .overlay(alignment: .bottomLeading) {
            Label(cameraLabel, systemImage: "video.fill")
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 10)
                .frame(minHeight: 36)
                .background(.regularMaterial, in: Capsule())
                .padding(10)
        }
        .clipped()
    }

    private var cameraLabel: String {
        if store.cameraImage != nil { return "Camera live" }
        if store.isDemoSession { return "Illustrative demo" }
        return "Connecting"
    }
}

private struct CameraWaitingPlate: View {
    let camera: String

    var body: some View {
        ZStack {
            Color(uiColor: .secondarySystemBackground)
            VStack(spacing: 10) {
                ProgressView()
                Text("Connecting \(camera) camera…")
                    .font(.subheadline.weight(.semibold))
                Text("Robot telemetry remains available while video reconnects.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(24)
        }
    }
}

private struct DemoCameraPlate: View {
    var body: some View {
        Canvas { context, size in
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(red: 0.78, green: 0.81, blue: 0.84)))
            let horizon = size.height * 0.37
            context.fill(Path(CGRect(x: 0, y: horizon, width: size.width, height: size.height - horizon)), with: .color(Color(red: 0.45, green: 0.48, blue: 0.5)))

            for index in 0..<8 {
                let amount = CGFloat(index) / 8
                var line = Path()
                line.move(to: CGPoint(x: size.width * amount, y: size.height))
                line.addLine(to: CGPoint(x: size.width * 0.5, y: horizon))
                context.stroke(line, with: .color(.white.opacity(0.2)), lineWidth: 1)
            }

            let robot = CGRect(x: size.width * 0.42, y: horizon - 30, width: size.width * 0.16, height: 92)
            context.fill(Path(roundedRect: robot, cornerRadius: 12), with: .color(.white.opacity(0.95)))
            context.fill(Path(ellipseIn: CGRect(x: robot.midX - 9, y: robot.minY - 30, width: 18, height: 36)), with: .color(AppPalette.navy))
            var arm = Path()
            arm.move(to: CGPoint(x: robot.midX, y: robot.minY))
            arm.addLine(to: CGPoint(x: robot.midX - 22, y: robot.minY - 52))
            arm.addLine(to: CGPoint(x: robot.midX + 12, y: robot.minY - 78))
            context.stroke(arm, with: .color(.white), style: StrokeStyle(lineWidth: 10, lineCap: .round, lineJoin: .round))
        }
    }
}
