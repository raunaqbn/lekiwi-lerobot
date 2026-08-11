import SwiftUI
import WebKit

struct TwinCameraAction: Equatable {
    let id = UUID()
    let command: String
}

struct TwinTelemetryView: View {
    @EnvironmentObject private var store: RobotStore
    @State private var cameraAction: TwinCameraAction?

    var body: some View {
        GeometryReader { proxy in
            if proxy.size.width > proxy.size.height {
                HStack(spacing: 0) {
                    modelPanel
                    Divider()
                    controlPanel
                        .frame(width: min(330, proxy.size.width * 0.4))
                }
            } else {
                VStack(spacing: 0) {
                    modelPanel
                    Divider()
                    controlPanel
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var modelPanel: some View {
        VStack(spacing: 0) {
            TwinWebView(
                state: store.state,
                selectedMotorID: $store.selectedMotorID,
                cameraAction: cameraAction
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(uiColor: .secondarySystemBackground))
            .accessibilityLabel("Interactive LeKiwi digital twin")
            MotorFocusStrip()
        }
    }

    private var controlPanel: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Model view")
                    .font(.subheadline.weight(.semibold))
                Text("Use these buttons for precise movement. You can still drag the model directly.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TwinCameraControls { command in
                    cameraAction = TwinCameraAction(command: command)
                }
            }
            .padding(12)
        }
        .background(Color(uiColor: .systemBackground))
    }
}

private struct TwinCameraControls: View {
    let send: (String) -> Void
    private let columns = [GridItem(.adaptive(minimum: 76, maximum: 120), spacing: 8)]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            control("Left", symbol: "rotate.left", command: "left")
            control("Right", symbol: "rotate.right", command: "right")
            control("Up", symbol: "arrow.up", command: "up")
            control("Down", symbol: "arrow.down", command: "down")
            control("Zoom in", symbol: "plus.magnifyingglass", command: "zoomIn")
            control("Zoom out", symbol: "minus.magnifyingglass", command: "zoomOut")
            control("Reset", symbol: "arrow.counterclockwise", command: "reset")
        }
    }

    private func control(_ label: String, symbol: String, command: String) -> some View {
        Button { send(command) } label: {
            VStack(spacing: 3) {
                Image(systemName: symbol)
                    .font(.headline)
                Text(label)
                    .font(.caption2.weight(.semibold))
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 48)
        }
        .buttonStyle(.bordered)
        .accessibilityLabel("Move 3D view \(label.lowercased())")
    }
}

private struct MotorFocusStrip: View {
    @EnvironmentObject private var store: RobotStore

    var body: some View {
        if let motor = store.selectedMotor {
            HStack(spacing: 10) {
                Image(systemName: symbol(for: motor.severity))
                    .foregroundStyle(color(for: motor.severity))
                VStack(alignment: .leading, spacing: 1) {
                    Text(motor.label)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                    Text("Motor ID \(motor.id) · tap a joint to inspect")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                if let position = motor.positionDegrees {
                    Text(motor.id == 6 ? String(format: "%.1f%%", position) : String(format: "%.1f°", position))
                        .font(.caption.monospacedDigit().weight(.semibold))
                }
                Label(motor.temperature.map { "\(Int($0))°C" } ?? "—", systemImage: "thermometer.medium")
                    .font(.caption2.monospacedDigit())
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 48)
            .background(Color(uiColor: .systemBackground))
            .accessibilityElement(children: .combine)
        }
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
        switch severity {
        case "warning": return AppPalette.warning
        case "critical": return AppPalette.critical
        default: return .secondary
        }
    }
}

struct TwinWebView: UIViewRepresentable {
    var state: GatewayState
    @Binding var selectedMotorID: Int
    var cameraAction: TwinCameraAction?

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.setURLSchemeHandler(context.coordinator.resourceHandler, forURLScheme: "lekiwi")
        configuration.userContentController.add(context.coordinator, name: "motorSelected")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.isOpaque = false
        view.backgroundColor = .clear
        view.scrollView.backgroundColor = .clear
        view.scrollView.isScrollEnabled = false
        view.scrollView.bounces = false
        if let html = URL(string: "lekiwi://resource/Twin/twin.html") {
            view.load(URLRequest(url: html))
        }
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.push(state, into: view)
        context.coordinator.send(cameraAction, into: view)
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "motorSelected")
        view.evaluateJavaScript("window.lekiwiTwin?.destroy()")
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var parent: TwinWebView
        let resourceHandler = TwinResourceSchemeHandler()
        private var ready = false
        private var pending: GatewayState?
        private var lastCameraActionID: UUID?

        init(parent: TwinWebView) { self.parent = parent }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            ready = true
            push(pending ?? parent.state, into: webView)
            pending = nil
            send(parent.cameraAction, into: webView)
        }

        func push(_ state: GatewayState, into webView: WKWebView) {
            guard ready else { pending = state; return }
            guard let data = try? JSONEncoder().encode(state), let json = String(data: data, encoding: .utf8) else { return }
            webView.evaluateJavaScript("window.lekiwiTwin?.update(\(json));")
        }

        func send(_ action: TwinCameraAction?, into webView: WKWebView) {
            guard ready, let action, action.id != lastCameraActionID else { return }
            lastCameraActionID = action.id
            webView.evaluateJavaScript("window.lekiwiTwin?.camera('\(action.command)');")
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "motorSelected", let body = message.body as? [String: Any], let id = body["id"] as? Int else { return }
            DispatchQueue.main.async { self.parent.selectedMotorID = id }
        }
    }
}

final class TwinResourceSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard
            let requestURL = urlSchemeTask.request.url,
            requestURL.scheme == "lekiwi",
            requestURL.host == "resource"
        else {
            urlSchemeTask.didFailWithError(URLError(.badURL))
            return
        }

        let encodedPath = requestURL.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard var relativePath = encodedPath.removingPercentEncoding else {
            urlSchemeTask.didFailWithError(URLError(.badURL))
            return
        }
        if relativePath.hasPrefix("static/models/") {
            relativePath.removeFirst("static/".count)
        }
        let root = Bundle.main.bundleURL.standardizedFileURL
        let fileURL = root.appendingPathComponent(relativePath).standardizedFileURL
        guard fileURL.path.hasPrefix(root.path), let data = try? Data(contentsOf: fileURL) else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }

        let mimeType: String
        switch fileURL.pathExtension.lowercased() {
        case "html": mimeType = "text/html"
        case "js": mimeType = "text/javascript"
        case "urdf", "xml": mimeType = "application/xml"
        case "stl": mimeType = "model/stl"
        default: mimeType = "application/octet-stream"
        }
        guard let response = HTTPURLResponse(
            url: requestURL,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: [
                "Content-Type": mimeType,
                "Content-Length": String(data.count),
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=31536000, immutable",
            ]
        ) else {
            urlSchemeTask.didFailWithError(URLError(.cannotParseResponse))
            return
        }
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}
}
