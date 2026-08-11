import AuthenticationServices
import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var store: RobotStore
    @StateObject private var authenticator = AccessWebAuthenticator()

    var body: some View {
        ZStack {
            AppPalette.mist.ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer(minLength: 28)

                VStack(spacing: 18) {
                    operatorRoute

                    VStack(spacing: 8) {
                        Text("Connect to LeKiwi")
                            .font(.largeTitle.bold())
                            .foregroundStyle(AppPalette.navy)
                            .multilineTextAlignment(.center)
                        Text("Sign in to the same secure robot workspace used by the web dashboard.")
                            .font(.body)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 330)
                    }
                }

                Spacer(minLength: 30)

                VStack(spacing: 12) {
                    if case let .failed(message) = store.authenticationState {
                        Label(message, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundStyle(AppPalette.critical)
                            .multilineTextAlignment(.center)
                            .padding(.bottom, 4)
                    } else if store.authenticationState == .expired {
                        Label("Your session expired. Sign in again to reconnect.", systemImage: "clock.badge.exclamationmark")
                            .font(.footnote)
                            .foregroundStyle(AppPalette.warning)
                            .multilineTextAlignment(.center)
                            .padding(.bottom, 4)
                    }

                    Button {
                        store.authenticationState = .authenticating
                        authenticator.start { result in
                            switch result {
                            case let .success(token):
                                store.completeAccessLogin(token: token)
                            case let .failure(error as ASWebAuthenticationSessionError)
                                where error.code == .canceledLogin:
                                store.authenticationState = .signedOut
                            case let .failure(error):
                                store.authenticationState = .failed(error.localizedDescription)
                            }
                        }
                    } label: {
                        HStack(spacing: 10) {
                            if store.authenticationState == .checking || store.authenticationState == .authenticating {
                                ProgressView().tint(.white)
                            } else {
                                Image(systemName: "lock.shield.fill")
                            }
                            Text(store.authenticationState == .checking ? "Checking session…" : "Sign in with Cloudflare Access")
                                .fontWeight(.semibold)
                        }
                        .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(AppPalette.indigo)
                    .disabled(store.authenticationState == .checking || store.authenticationState == .authenticating)

                    Label("Google passkeys open in the secure iOS sign-in window.", systemImage: "faceid")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Button("Preview the interface") {
                        store.useDemo()
                    }
                    .buttonStyle(.bordered)
                    .frame(minHeight: 44)
                }
                .frame(maxWidth: 430)

                Spacer(minLength: 30)

                Label("Stay near the robot and keep its physical power cutoff within reach.", systemImage: "hand.raised.fill")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 360)
                    .padding(.bottom, 18)
            }
            .padding(.horizontal, 24)
        }
    }

    private var operatorRoute: some View {
        HStack(spacing: 10) {
            Image(systemName: "iphone.gen3")
                .font(.title2)
                .frame(width: 54, height: 54)
                .background(.background, in: RoundedRectangle(cornerRadius: 14))

            HStack(spacing: 4) {
                Circle().fill(AppPalette.indigo).frame(width: 7, height: 7)
                Rectangle().fill(AppPalette.indigo.opacity(0.45)).frame(height: 2)
                Image(systemName: "lock.fill")
                    .font(.caption)
                    .foregroundStyle(AppPalette.indigo)
                Rectangle().fill(AppPalette.indigo.opacity(0.45)).frame(height: 2)
                Circle().fill(AppPalette.indigo).frame(width: 7, height: 7)
            }
            .frame(maxWidth: 150)
            .accessibilityHidden(true)

            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.title2)
                .foregroundStyle(AppPalette.indigo)
                .frame(width: 54, height: 54)
                .background(.background, in: RoundedRectangle(cornerRadius: 14))
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Secure connection from this iPhone to the LeKiwi robot")
    }
}

@MainActor
private final class AccessWebAuthenticator: NSObject, ObservableObject,
    ASWebAuthenticationPresentationContextProviding
{
    private var session: ASWebAuthenticationSession?

    func start(completion: @escaping (Result<String, Error>) -> Void) {
        session?.cancel()
        let state = UUID().uuidString.replacingOccurrences(of: "-", with: "")
        let session = ASWebAuthenticationSession(
            url: RobotService.authenticationURL(state: state),
            callbackURLScheme: AccessCallback.scheme
        ) { callbackURL, error in
            Task { @MainActor in
                self.session = nil
                if let error {
                    completion(.failure(error))
                    return
                }
                guard let callbackURL else {
                    completion(.failure(AccessLoginError.invalidCallback))
                    return
                }
                do {
                    completion(.success(try AccessCallback.token(from: callbackURL, expectedState: state)))
                } catch {
                    completion(.failure(error))
                }
            }
        }
        session.presentationContextProvider = self
        session.prefersEphemeralWebBrowserSession = false
        self.session = session
        guard session.start() else {
            self.session = nil
            completion(.failure(AccessLoginError.invalidCallback))
            return
        }
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        if let keyWindow = scenes.flatMap(\.windows).first(where: \.isKeyWindow) {
            return keyWindow
        }
        return scenes.first?.windows.first ?? ASPresentationAnchor(frame: .zero)
    }
}
