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

    /// `GET /api/runner`: every engine, usable or why not, as the server sees it.
    public func runner() async throws -> RunnerStatus {
        try await get("api/runner")
    }

    /// `GET /api/models`: the curated model list per engine and the office's defaults.
    public func models() async throws -> ModelCatalog {
        try await get("api/models")
    }

    /// `GET /api/config`: `office.toml` settings and the names of stored secrets, with every
    /// secret value masked by the server.
    public func config() async throws -> JSONValue {
        try await get("api/config")
    }

    /// `GET /api/devices`: the paired phones. Needs the launch cookie.
    public func devices() async throws -> [Device] {
        let list: DeviceList = try await get("api/devices")
        return list.devices
    }

    /// `GET /api/runs`: advisor runs, newest first. A server without chat answers with an error.
    public func runs() async throws -> [RunSummary] {
        try await get("api/runs")
    }

    /// `POST /api/devices/pairing`: a new five-minute pairing code. Loopback and cookie only;
    /// it replaces any code still outstanding.
    public func requestPairingCode() async throws -> PairingCode {
        try await send("POST", "api/devices/pairing")
    }

    /// `DELETE /api/devices/{id}`: revokes a paired phone; its next request fails.
    @discardableResult
    public func revokeDevice(id: String) async throws -> DeviceRevocation {
        try await send("DELETE", "api/devices/\(id)")
    }

    func get<T: Decodable>(_ path: String) async throws -> T {
        try await send("GET", path)
    }

    /// `http://127.0.0.1:PORT`, the Origin a page from this server sends.
    var origin: String {
        var components = URLComponents()
        components.scheme = baseURL.scheme
        components.host = baseURL.host
        components.port = baseURL.port
        return components.string ?? ""
    }

    /// `POST /api/devices/pair` over the tailnet: redeems a pairing code for a device token,
    /// which the server shows only in this response. Sends no cookie and no Origin; the server
    /// checks the Tailscale identity that `tailscale serve` adds.
    public func pair(code: String, name: String) async throws -> DeviceToken {
        let body = try JSONEncoder().encode(["code": code, "name": name])
        let (data, _) = try await perform("POST", "api/devices/pair", body: body, credential: .none)
        return try Self.decode(DeviceToken.self, from: data)
    }

    /// `POST /api/devices/login` with `Authorization: Bearer <token>`: trades the device token
    /// for a per-device session cookie. The client keeps the cookie for its later requests and
    /// returns it so the web view can use the same session.
    public func login(token: String) async throws -> (DeviceLogin, [HTTPCookie]) {
        let (data, response) = try await perform(
            "POST", "api/devices/login", body: nil, credential: .bearer(token))
        let login = try Self.decode(DeviceLogin.self, from: data)
        var fields: [String: String] = [:]
        for (key, value) in response.allHeaderFields {
            if let key = key as? String, let value = value as? String { fields[key] = value }
        }
        let url = response.url ?? baseURL
        let cookies = HTTPCookie.cookies(withResponseHeaderFields: fields, for: url)
        self.cookies.replace(cookies)
        return (login, cookies)
    }

    enum Credential {
        /// The copied session cookie; writes also carry the server's own origin.
        case cookie
        /// A bearer token and nothing else (the device login).
        case bearer(String)
        /// No credential at all (pairing).
        case none
    }

    /// Sends one request with the copied session cookie. Writes also carry the server's own
    /// origin, which the server requires on every non-GET request.
    func send<T: Decodable>(_ method: String, _ path: String) async throws -> T {
        let (data, _) = try await perform(method, path, body: nil, credential: .cookie)
        return try Self.decode(T.self, from: data)
    }

    func perform(_ method: String, _ path: String, body: Data?, credential: Credential)
        async throws -> (Data, HTTPURLResponse)
    {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        switch credential {
        case .cookie:
            if method != "GET" {
                request.setValue(origin, forHTTPHeaderField: "Origin")
            }
            for (field, value) in HTTPCookie.requestHeaderFields(with: cookies.current) {
                request.setValue(value, forHTTPHeaderField: field)
            }
        case .bearer(let token):
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        case .none:
            break
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
        return (data, http)
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
