import Foundation
import Security
import WebKit

enum RobotService {
    static let baseURL: URL = {
        let configured = Bundle.main.object(forInfoDictionaryKey: "LeKiwiBaseURL") as? String
        guard let configured, let url = URL(string: configured), url.scheme == "https" else {
            preconditionFailure("LeKiwiBaseURL must be an https URL in Info.plist")
        }
        return url
    }()
    static let host = baseURL.host!

    static func url(path: String) -> URL {
        baseURL.appending(path: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }

    static func authenticationURL(state: String) -> URL {
        var components = URLComponents(
            url: url(path: "api/mobile/auth"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "state", value: state)]
        return components.url!
    }
}

enum AccessAuthenticationState: Equatable {
    case checking
    case signedOut
    case authenticating
    case authenticated
    case expired
    case failed(String)
}

enum AccessLoginError: LocalizedError {
    case invalidCallback
    case stateMismatch
    case missingToken
    case tokenStorageFailed

    var errorDescription: String? {
        switch self {
        case .invalidCallback:
            return "Cloudflare returned an invalid sign-in callback."
        case .stateMismatch:
            return "The sign-in response could not be verified. Please try again."
        case .missingToken:
            return "Cloudflare did not return an Access session."
        case .tokenStorageFailed:
            return "The secure Access session could not be saved on this iPhone."
        }
    }
}

enum AccessCallback {
    static let scheme: String = {
        guard let configured = Bundle.main.object(forInfoDictionaryKey: "LeKiwiCallbackScheme") as? String,
              !configured.isEmpty else {
            preconditionFailure("LeKiwiCallbackScheme must be configured in Info.plist")
        }
        return configured
    }()

    static func token(from url: URL, expectedState: String) throws -> String {
        guard url.scheme == scheme, url.host == "access", url.path == "/callback" else {
            throw AccessLoginError.invalidCallback
        }
        guard let fragment = url.fragment,
              let values = URLComponents(string: "?\(fragment)")?.queryItems else {
            throw AccessLoginError.invalidCallback
        }
        let state = values.first(where: { $0.name == "state" })?.value
        guard state == expectedState else {
            throw AccessLoginError.stateMismatch
        }
        guard let token = values.first(where: { $0.name == "token" })?.value,
              token.split(separator: ".").count == 3 else {
            throw AccessLoginError.missingToken
        }
        return token
    }
}

enum AccessTokenStore {
    private static let service = "\(Bundle.main.bundleIdentifier ?? "io.lekiwi.controller").cloudflare-access"
    private static let account = "cf-access-token"

    static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    static func save(_ token: String) throws {
        clear()
        let attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            kSecValueData as String: Data(token.utf8),
        ]
        guard SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess else {
            throw AccessLoginError.tokenStorageFailed
        }
    }

    static func clear() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

@MainActor
enum AccessCookieManager {
    private static func webKitCookies() async -> [HTTPCookie] {
        await withCheckedContinuation { continuation in
            WKWebsiteDataStore.default().httpCookieStore.getAllCookies { cookies in
                continuation.resume(returning: cookies)
            }
        }
    }

    static func synchronizeToFoundation() async {
        let cookies = await webKitCookies()
        for cookie in cookies where isAccessCookie(cookie) {
            HTTPCookieStorage.shared.setCookie(cookie)
        }
    }

    static func clear() async {
        AccessTokenStore.clear()
        let webStore = WKWebsiteDataStore.default().httpCookieStore
        let cookies = await webKitCookies()
        for cookie in cookies where isAccessCookie(cookie) {
            await withCheckedContinuation { continuation in
                webStore.delete(cookie) {
                    continuation.resume()
                }
            }
        }

        for cookie in HTTPCookieStorage.shared.cookies ?? [] where isAccessCookie(cookie) {
            HTTPCookieStorage.shared.deleteCookie(cookie)
        }
    }

    private static func isAccessCookie(_ cookie: HTTPCookie) -> Bool {
        let domain = cookie.domain.lowercased()
        return domain.hasSuffix(RobotService.host.lowercased()) || domain.hasSuffix("cloudflareaccess.com")
    }
}

enum RobotNetworkError: LocalizedError {
    case authenticationRequired
    case unexpectedResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .authenticationRequired:
            return "Your Cloudflare Access session has expired. Sign in again to reconnect."
        case .unexpectedResponse:
            return "The robot service returned an unexpected response."
        case let .server(message):
            return message
        }
    }
}

func authenticatedRobotResponse(
    _ response: URLResponse,
    contentTypes: [String]
) throws -> HTTPURLResponse {
    guard let http = response as? HTTPURLResponse else {
        throw RobotNetworkError.unexpectedResponse
    }
    guard http.url?.host == RobotService.host else {
        throw RobotNetworkError.authenticationRequired
    }
    guard http.statusCode == 200 else {
        if http.statusCode == 401 || http.statusCode == 403 || http.statusCode == 302 {
            throw RobotNetworkError.authenticationRequired
        }
        throw RobotNetworkError.server("Robot service returned HTTP \(http.statusCode).")
    }
    let responseType = http.value(forHTTPHeaderField: "Content-Type")?.lowercased() ?? ""
    guard contentTypes.contains(where: responseType.contains) else {
        throw RobotNetworkError.unexpectedResponse
    }
    return http
}

func authenticatedRobotResponse(_ response: URLResponse, contentType: String) throws -> HTTPURLResponse {
    try authenticatedRobotResponse(response, contentTypes: [contentType])
}
