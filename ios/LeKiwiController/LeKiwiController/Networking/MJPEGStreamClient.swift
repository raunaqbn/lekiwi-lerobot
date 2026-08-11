import Foundation

struct JPEGFrameParser {
    private static let startMarker = Data([0xFF, 0xD8])
    private static let endMarker = Data([0xFF, 0xD9])
    private(set) var buffer = Data()

    mutating func append(_ data: Data) -> [Data] {
        buffer.append(data)
        var frames: [Data] = []

        while let start = buffer.range(of: Self.startMarker)?.lowerBound {
            if start > buffer.startIndex {
                buffer.removeSubrange(buffer.startIndex..<start)
            }
            guard let endRange = buffer.range(
                of: Self.endMarker,
                in: buffer.index(buffer.startIndex, offsetBy: 2)..<buffer.endIndex
            ) else {
                break
            }
            let end = endRange.upperBound
            frames.append(buffer.subdata(in: buffer.startIndex..<end))
            buffer.removeSubrange(buffer.startIndex..<end)
        }

        if buffer.count > 8 * 1024 * 1024 {
            if let start = buffer.range(of: Self.startMarker, options: .backwards)?.lowerBound {
                buffer.removeSubrange(buffer.startIndex..<start)
            } else {
                buffer = Data(buffer.suffix(1))
            }
        }
        return frames
    }
}

final class MJPEGStreamClient: NSObject, URLSessionDataDelegate {
    var onFrame: ((Data) -> Void)?
    var onAuthenticationRequired: ((String) -> Void)?
    var onFailure: ((Error) -> Void)?

    private var parser = JPEGFrameParser()
    private var session: URLSession?
    private var task: URLSessionDataTask?

    func start(url: URL, headers: [String: String] = [:]) {
        stop()
        parser = JPEGFrameParser()
        let configuration = URLSessionConfiguration.default
        configuration.httpCookieStorage = .shared
        configuration.httpShouldSetCookies = true
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        self.session = session
        var request = URLRequest(url: url)
        for (name, value) in headers {
            request.setValue(value, forHTTPHeaderField: name)
        }
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 15
        let task = session.dataTask(with: request)
        self.task = task
        task.resume()
    }

    func stop() {
        task?.cancel()
        task = nil
        session?.invalidateAndCancel()
        session = nil
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        do {
            // URLSession reports the outer MJPEG response and may also report each MIME part.
            // Both are valid camera responses and must remain on the same stream.
            _ = try authenticatedRobotResponse(
                response,
                contentTypes: ["multipart/x-mixed-replace", "image/jpeg"]
            )
            completionHandler(.allow)
        } catch RobotNetworkError.authenticationRequired {
            completionHandler(.cancel)
            let http = response as? HTTPURLResponse
            let detail = [
                "status=\(http?.statusCode ?? -1)",
                "host=\(http?.url?.host ?? "missing")",
                "type=\(http?.value(forHTTPHeaderField: "Content-Type") ?? "missing")",
            ].joined(separator: " ")
            DispatchQueue.main.async { self.onAuthenticationRequired?(detail) }
        } catch {
            completionHandler(.cancel)
            DispatchQueue.main.async { self.onFailure?(error) }
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        let frames = parser.append(data)
        for frame in frames {
            DispatchQueue.main.async { self.onFrame?(frame) }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error, (error as? URLError)?.code != .cancelled else { return }
        DispatchQueue.main.async { self.onFailure?(error) }
    }
}
