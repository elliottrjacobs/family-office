import Foundation
import Observation

/// `POST /api/devices/pair` returns `{"id": "dev_…", "token": "…", "name": "…"}`. The token is
/// shown only in this response; the phone moves it straight to the Keychain.
public struct DeviceToken: Codable, Sendable, Equatable {
    public let id: String
    public let token: String
    public let name: String?

    public init(id: String, token: String, name: String?) {
        self.id = id
        self.token = token
        self.name = name
    }
}

extension DeviceToken: CustomStringConvertible, CustomDebugStringConvertible {
    /// Never includes the token.
    public var description: String { "DeviceToken(id: \(id))" }
    public var debugDescription: String { description }
}

/// `POST /api/devices/login` returns `{"id": "dev_…", "name": "…", "server_version": "…"}`
/// and sets the device's session cookie.
public struct DeviceLogin: Codable, Sendable, Equatable {
    public let id: String
    public let name: String?
    public let serverVersion: String?

    public init(id: String, name: String?, serverVersion: String?) {
        self.id = id
        self.name = name
        self.serverVersion = serverVersion
    }

    private enum CodingKeys: String, CodingKey {
        case id, name
        case serverVersion = "server_version"
    }
}

/// A `major.minor.patch` package version. A pre-release suffix (`2.0.0a1`) is ignored, so a
/// pre-release compares equal to its release.
public struct ServerVersion: Comparable, Sendable, CustomStringConvertible {
    public let major: Int
    public let minor: Int
    public let patch: Int

    public init(_ major: Int, _ minor: Int, _ patch: Int = 0) {
        self.major = major
        self.minor = minor
        self.patch = patch
    }

    /// Parses `2.0.0`, `2.1` or `2.0.0a1`; nil for anything without a leading number.
    public init?(_ text: String) {
        var numbers: [Int] = []
        for part in text.trimmingCharacters(in: .whitespaces).split(separator: ".").prefix(3) {
            let digits = part.prefix { $0.isASCII && $0.isNumber }
            guard let value = Int(digits) else { break }
            numbers.append(value)
            if digits.count != part.count { break }
        }
        guard let major = numbers.first else { return nil }
        self.init(
            major, numbers.count > 1 ? numbers[1] : 0, numbers.count > 2 ? numbers[2] : 0)
    }

    public static func < (lhs: ServerVersion, rhs: ServerVersion) -> Bool {
        (lhs.major, lhs.minor, lhs.patch) < (rhs.major, rhs.minor, rhs.patch)
    }

    public var description: String { "\(major).\(minor).\(patch)" }
}

/// Why a pairing or login did not succeed, in words the phone shows as they are.
public enum DeviceSessionError: Error, Equatable, Sendable {
    /// There is no paired Mac to log in to.
    case notPaired
    /// The Mac did not answer; the phone stays paired.
    case unreachable(String)
    /// The Mac answered but refused; the phone stays as it was.
    case refused(String)
    /// The Mac no longer knows this phone (a login 401); the credential is gone.
    case unpaired(String)

    public var message: String {
        switch self {
        case .notPaired: return "This iPhone is not paired with a Mac."
        case .unreachable(let text), .refused(let text), .unpaired(let text): return text
        }
    }
}

/// The phone's pairing state machine: unpaired, pairing with a scanned code, or paired with a
/// device token in the credential store.
///
/// `pair(payload:name:)` redeems the code over the tailnet and stores the token;
/// `login()` trades the token for the session cookie the web view uses. A cookie 401 from
/// the web view or a status probe asks the phone to re-login once with the stored token,
/// until a status probe succeeds or the user retries. Only a 401 from `login()` forgets the
/// Keychain token and returns to `unpaired` with the reason, so a revoked phone pairs again.
/// Codes and tokens are never logged or put in an error.
@MainActor
@Observable
public final class DeviceSession {
    public enum State: Equatable, Sendable, CustomStringConvertible {
        /// The credential could not be read yet; retry when the app becomes active.
        case credentialUnavailable
        case unpaired(reason: String?)
        case pairing(url: URL, code: String)
        case paired(url: URL, deviceId: String, name: String)

        /// Never includes the code.
        public var description: String {
            switch self {
            case .credentialUnavailable: return "credentialUnavailable"
            case .unpaired(let reason): return "unpaired(\(reason == nil ? "" : "with reason"))"
            case .pairing(let url, _): return "pairing(\(url))"
            case .paired(let url, let deviceId, _): return "paired(\(url), \(deviceId))"
            }
        }
    }

    /// The server versions this build was made against: 2.0.x. A newer server still works,
    /// but the app advises an update because the web app and routes may have moved on.
    public nonisolated static let knownServerVersions = ServerVersion(2, 0, 0)..<ServerVersion(2, 1, 0)

    /// What a 403 `forbidden_login` means on a phone: the request reached the Mac without a
    /// Tailscale identity it accepts.
    public nonisolated static let identityExplanation =
        "The Mac did not receive a Tailscale identity it accepts. Open Tailscale on this iPhone, "
        + "sign in with an account the Mac's office allows, and scan a new code."

    /// What a login 401 means after pairing: the Mac revoked this phone, or never knew it.
    public nonisolated static let revokedExplanation =
        "This iPhone is no longer paired with the Mac. It may have been revoked in "
        + "Settings > Devices. Pair it again to continue."

    public nonisolated static let credentialUnavailableExplanation =
        "The Keychain is not available. Unlock this iPhone and try again."

    public private(set) var state: State
    /// The version the server reported at the last login.
    public private(set) var serverVersion: String?
    /// The session cookies from the last login, for the web view.
    public private(set) var cookies: [HTTPCookie] = []

    private let store: CredentialStore
    private let timeout: TimeInterval
    private let protocolClasses: [AnyClass]?
    private var client: APIClient?

    /// - Parameters:
    ///   - store: where the credential lives (`Keychain()` in the app).
    ///   - timeout: per-request timeout in seconds.
    ///   - protocolClasses: test stubs; nil uses the system stack.
    public init(store: CredentialStore, timeout: TimeInterval = 10, protocolClasses: [AnyClass]? = nil)
    {
        self.store = store
        self.timeout = timeout
        self.protocolClasses = protocolClasses
        state = .credentialUnavailable
        restoreCredential()
    }

    /// Retry a failed credential read when the app becomes active. In particular,
    /// `errSecInteractionNotAllowed` while the device is locked does not mean unpaired.
    public func restoreCredential() {
        guard case .credentialUnavailable = state else { return }
        do {
            if let credential = try store.read() {
                state = .paired(url: credential.url, deviceId: credential.deviceId, name: credential.name)
            } else {
                state = .unpaired(reason: nil)
            }
        } catch {
            // Every read failure is non-destructive, including decoding failures.
            state = .credentialUnavailable
        }
    }

    /// True when the server is newer than `knownServerVersions`.
    public var updateAdvised: Bool {
        Self.updateAdvised(for: serverVersion)
    }

    public nonisolated static func updateAdvised(for version: String?) -> Bool {
        guard let version, let parsed = ServerVersion(version) else { return false }
        return parsed >= knownServerVersions.upperBound
    }

    /// The paired server's URL, if any.
    public var url: URL? {
        switch state {
        case .paired(let url, _, _), .pairing(let url, _): return url
        case .credentialUnavailable, .unpaired: return nil
        }
    }

    /// A client for the paired server that carries the session cookie after `login()`.
    public var apiClient: APIClient? {
        guard case .paired(let url, _, _) = state else { return nil }
        return client(for: url)
    }

    private func client(for url: URL) -> APIClient {
        if let client, client.baseURL == url { return client }
        let made = APIClient(baseURL: url, timeout: timeout, protocolClasses: protocolClasses)
        client = made
        return made
    }

    /// Redeems the scanned code at `payload.url` and stores the device token. On failure the
    /// session returns to `unpaired` with the reason and the error carries the same words.
    public func pair(payload: PairingPayload, name: String) async throws {
        guard let url = URL(string: payload.url) else {
            throw fail(.refused("The code does not contain a valid address."))
        }
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        state = .pairing(url: url, code: payload.code)
        let api = client(for: url)
        let token: DeviceToken
        do {
            token = try await api.pair(code: payload.code, name: name)
        } catch {
            throw fail(Self.pairingError(error))
        }
        let credential = DeviceCredential(
            url: url, deviceId: token.id, name: token.name ?? name, token: token.token)
        do {
            try store.write(credential)
        } catch {
            throw fail(.refused("The Keychain refused the device token. Pair again."))
        }
        cookies = []
        serverVersion = nil
        state = .paired(url: url, deviceId: credential.deviceId, name: credential.name)
    }

    /// Trades the stored token for the session cookie and returns the server's version. Only
    /// a 401 from this login forgets the Keychain token and returns to `unpaired`; a transport
    /// failure leaves the phone paired. Cookie 401s from the web view or a status probe ask
    /// the phone to try this login once with the stored token before waiting for Retry.
    @discardableResult
    public func login() async throws -> String? {
        guard case .paired(let url, _, _) = state else { throw DeviceSessionError.notPaired }
        let credential: DeviceCredential?
        do {
            credential = try store.read()
        } catch {
            throw DeviceSessionError.refused(Self.credentialUnavailableExplanation)
        }
        guard let credential, credential.url == url else {
            throw DeviceSessionError.refused(
                "This iPhone's device token is missing or changed. Try again or unpair this iPhone.")
        }
        do {
            let (login, cookies) = try await client(for: url).login(token: credential.token)
            self.cookies = cookies
            serverVersion = login.serverVersion
            return login.serverVersion
        } catch APIError.http(401, _) {
            throw unauthorized(reason: Self.revokedExplanation)
        } catch APIError.http(let status, let reason) {
            throw DeviceSessionError.refused(Self.refusal(status: status, reason: reason))
        } catch APIError.transport(let detail) {
            throw DeviceSessionError.unreachable(Self.unreachable(detail))
        } catch {
            throw DeviceSessionError.refused("The Mac's answer was not understood.")
        }
    }

    /// A 401 from the token login: forgets the Keychain token and returns
    /// to `unpaired` with `reason`. Cookie 401s from the web view or a status probe trigger one
    /// re-login with the stored token instead. Returns the matching error for callers to throw.
    @discardableResult
    public func unauthorized(reason: String? = nil) -> DeviceSessionError {
        let text = reason ?? Self.revokedExplanation
        forget()
        state = .unpaired(reason: text)
        return .unpaired(text)
    }

    /// Forgets the token on this phone only. The Mac keeps listing the device until it is
    /// revoked there.
    public func unpair() {
        forget()
        state = .unpaired(reason: nil)
    }

    private func forget() {
        try? store.delete()
        cookies = []
        serverVersion = nil
        client = nil
    }

    private func fail(_ error: DeviceSessionError) -> DeviceSessionError {
        state = .unpaired(reason: error.message)
        return error
    }

    nonisolated static func pairingError(_ error: Error) -> DeviceSessionError {
        switch error {
        case APIError.http(_, "forbidden_login"?):
            return .refused(identityExplanation)
        case APIError.http(_, "tailnet_only"?):
            return .refused(
                "The Mac is not accepting phones yet. Turn on phone access in Family Office on the "
                    + "Mac (Settings > General), then scan a new code.")
        case APIError.http(_, "invalid_pairing_code"?):
            return .refused(
                "That code is wrong, used or expired. Show a new one on the Mac with "
                    + "Settings > Devices > Pair a Phone.")
        case APIError.http(_, "invalid_request"?):
            return .refused("The Mac refused this iPhone's name. Use 1 to 64 printable characters.")
        case APIError.http(let status, let reason):
            return .refused(refusal(status: status, reason: reason))
        case APIError.transport(let detail):
            return .unreachable(unreachable(detail))
        default:
            return .refused("The Mac's answer was not understood.")
        }
    }

    nonisolated static func refusal(status: Int, reason: String?) -> String {
        switch reason {
        case "forbidden_login"?: return identityExplanation
        case "misdirected_request"?:
            return "The address is not the Mac's tailnet name. Check the name in Settings > Devices on the Mac."
        case "tailnet_only"?, "unauthorized"?:
            return "The Mac accepts this iPhone only through its tailnet address with phone access on."
        default:
            return Pairing.explain(APIError.http(status: status, reason: reason))
        }
    }

    nonisolated static func unreachable(_ detail: String) -> String {
        "The Mac did not answer (\(detail)). It must be awake and on your tailnet, with Family Office open."
    }
}

extension PairingPayload {
    /// A payload typed by hand, for a simulator or a phone without a camera. The URL is the
    /// Mac's tailnet address; `https://` is assumed when no scheme is given, and plain `http`
    /// is accepted only for `localhost` or `127.0.0.1`, which a simulator shares with the Mac.
    /// The code keeps only its letters and digits, upper-cased: the server ignores the hyphen
    /// the Mac shows, and a keyboard may turn it into a dash.
    public static func manual(url: String, code: String) throws -> PairingPayload {
        var text = url.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.contains("://") {
            text = "https://" + text
        }
        guard var components = URLComponents(string: text), let host = components.host,
            !host.isEmpty
        else { throw DecodeError.invalid("url") }
        let scheme = components.scheme?.lowercased()
        let loopback = ["localhost", "127.0.0.1"].contains(host.lowercased())
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw DecodeError.invalid("url")
        }
        components.path = ""
        components.query = nil
        components.fragment = nil
        components.user = nil
        components.password = nil
        guard let clean = components.string else { throw DecodeError.invalid("url") }
        let cleaned = code.uppercased().filter { $0.isASCII && ($0.isLetter || $0.isNumber) }
        guard !cleaned.isEmpty else { throw DecodeError.invalid("code") }
        return PairingPayload(url: clean, code: cleaned)
    }
}
