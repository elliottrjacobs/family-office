import Foundation

/// Errors from `APIClient`. None of them carries a token or cookie value.
public enum APIError: Error, Equatable, Sendable {
    /// The request never got an HTTP response (connection refused, timeout, ...).
    case transport(String)
    /// The server answered with a non-2xx status; `reason` is the server's machine reason.
    case http(status: Int, reason: String?)
    /// The body did not match the expected type.
    case decoding(type: String, detail: String)
}

/// A thin client for the JSON routes of `fo serve`.
///
/// Authentication is the server's session cookie, set when the web view loads the landing
/// URL. The client never sends the handshake token itself: the app copies the cookie from
/// the web view's store with `setCookies(_:)`. Cookies are held in memory only.
public final class APIClient: Sendable {
    public let baseURL: URL
    private let session: URLSession
    private let cookies = CookieJar()

    /// - Parameters:
    ///   - baseURL: the server origin, normally `Handshake.baseURL`.
    ///   - timeout: per-request timeout in seconds.
    ///   - protocolClasses: test stubs; nil uses the system stack.
    public init(baseURL: URL, timeout: TimeInterval = 10, protocolClasses: [AnyClass]? = nil) {
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout
        configuration.connectionProxyDictionary = [:]
        if let protocolClasses {
            configuration.protocolClasses = protocolClasses
        }
        self.session = URLSession(configuration: configuration)
    }

    public convenience init(handshake: Handshake, timeout: TimeInterval = 10) {
        self.init(baseURL: handshake.baseURL, timeout: timeout)
    }

    deinit {
        session.invalidateAndCancel()
    }

    /// Replaces the client's cookies with the server-origin cookies given.
    public func setCookies(_ cookies: [HTTPCookie]) {
        let host = baseURL.host ?? ""
        self.cookies.replace(cookies.filter { $0.domain == host || $0.domain == ".\(host)" })
    }

    public var hasSessionCookie: Bool {
        !cookies.current.isEmpty
    }

    public func status() async throws -> ServerStatus {
        try await get("api/status")
    }

    public func onboarding() async throws -> Onboarding {
        try await get("api/onboarding")
    }

    public func devices() async throws -> [Device] {
        let list: DeviceList = try await get("api/devices")
        return list.devices
    }

    func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        for (field, value) in HTTPCookie.requestHeaderFields(with: cookies.current) {
            request.setValue(value, forHTTPHeaderField: field)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            throw APIError.transport(Self.describe(error))
        } catch {
            throw APIError.transport("request failed")
        }
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport("not an HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            let denial = try? JSONDecoder().decode(Denial.self, from: data)
            throw APIError.http(status: http.statusCode, reason: denial?.reason)
        }
        return try Self.decode(T.self, from: data)
    }

    /// Decodes a response body, mapping failures to `APIError.decoding`.
    public static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch let error as DecodingError {
            throw APIError.decoding(type: String(describing: type), detail: describe(error))
        } catch {
            throw APIError.decoding(type: String(describing: type), detail: "invalid body")
        }
    }

    private struct Denial: Decodable {
        let reason: String?
    }

    // URLError descriptions can embed the request URL; keep only the code.
    private static func describe(_ error: URLError) -> String {
        switch error.code {
        case .timedOut: return "timed out"
        case .cannotConnectToHost: return "connection refused"
        case .networkConnectionLost: return "connection lost"
        case .cancelled: return "cancelled"
        default: return "URL error \(error.code.rawValue)"
        }
    }

    private static func describe(_ error: DecodingError) -> String {
        func path(_ context: DecodingError.Context) -> String {
            context.codingPath.map(\.stringValue).joined(separator: ".")
        }
        switch error {
        case .keyNotFound(let key, let context):
            let prefix = path(context)
            return "missing \(prefix.isEmpty ? key.stringValue : prefix + "." + key.stringValue)"
        case .typeMismatch(_, let context), .valueNotFound(_, let context):
            return "wrong type at \(path(context))"
        case .dataCorrupted:
            return "not valid JSON"
        @unknown default:
            return "undecodable"
        }
    }
}

/// The client's in-memory cookies, safe to use from any thread.
final class CookieJar: @unchecked Sendable {
    private let lock = NSLock()
    private var cookies: [HTTPCookie] = []

    var current: [HTTPCookie] {
        lock.withLock { cookies }
    }

    func replace(_ new: [HTTPCookie]) {
        lock.withLock { cookies = new }
    }
}
