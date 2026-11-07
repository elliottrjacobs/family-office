import Foundation
import XCTest

@testable import FOKit

/// A tiny stand-in for `fo serve`'s device routes: a handler per request, and a record of
/// every request with its body.
final class DeviceStub: URLProtocol, @unchecked Sendable {
    struct Reply {
        var status: Int
        var headers: [String: String] = [:]
        var body: Data
    }

    struct Seen {
        let method: String
        let path: String
        let headers: [String: String]
        let body: Data?
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var handler: (@Sendable (Seen) -> Reply?)?
    nonisolated(unsafe) private static var seen: [Seen] = []

    static func serve(_ handler: @escaping @Sendable (Seen) -> Reply?) {
        lock.withLock {
            self.handler = handler
            seen = []
        }
    }

    static var requests: [Seen] { lock.withLock { seen } }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let body = request.httpBody ?? request.httpBodyStream.map(Self.read)
        let seen = Seen(
            method: request.httpMethod ?? "GET", path: request.url?.path ?? "",
            headers: request.allHTTPHeaderFields ?? [:], body: body)
        let reply = Self.lock.withLock { () -> Reply? in
            Self.seen.append(seen)
            return Self.handler?(seen)
        }
        guard let reply, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        var headers = reply.headers
        headers["Content-Type"] = "application/json"
        let response = HTTPURLResponse(
            url: url, statusCode: reply.status, httpVersion: "HTTP/1.1", headerFields: headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func read(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }
}

/// A file-backed credential store standing in for the Keychain, which `swift test` on macOS
/// cannot use without a signed host. Written at 0600, like the real item is device-only.
final class FileCredentialStore: CredentialStore, @unchecked Sendable {
    let url: URL

    init(directory: URL) {
        url = directory.appendingPathComponent("credential.json")
    }

    func read() throws -> DeviceCredential? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try JSONDecoder().decode(DeviceCredential.self, from: Data(contentsOf: url))
    }

    func write(_ credential: DeviceCredential) throws {
        try JSONEncoder().encode(credential).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    func delete() throws {
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }
}

@MainActor
final class DeviceSessionTests: XCTestCase {
    private let host = "example-mac.tail0000.ts.net"
    private var directory: URL!
    private var store: FileCredentialStore!

    // Synthetic values; never real codes or tokens.
    private let code = "ABCD2345"
    private let token = "synthetic-device-token-0000"

    override func setUp() async throws {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("fokit-device-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        store = FileCredentialStore(directory: directory)
        DeviceStub.serve { _ in nil }
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func session() -> DeviceSession {
        DeviceSession(store: store, timeout: 2, protocolClasses: [DeviceStub.self])
    }

    private var payload: PairingPayload {
        PairingPayload.init(tailnetName: host, code: code)
    }

    /// A server that pairs, logs in with `version`, and answers 401 once `revoked` is set.
    private func serveDevices(version: String = "2.0.0a1", revoked: @escaping @Sendable () -> Bool = { false }) {
        let token = self.token
        let statusBody = try! Data(
            contentsOf: Bundle.module.url(forResource: "Fixtures/status", withExtension: "json")!)
        DeviceStub.serve { seen in
            switch (seen.method, seen.path) {
            case ("POST", "/api/devices/pair"):
                return .init(status: 200, body: stubJSON(["id": "dev_0001", "token": token, "name": "Test iPhone"]))
            case ("POST", "/api/devices/login"):
                if revoked() || seen.headers["Authorization"] != "Bearer \(token)" {
                    return .init(status: 401, body: stubJSON(["reason": "unknown_device", "message": "x"]))
                }
                return .init(
                    status: 200,
                    headers: ["Set-Cookie": "fo_session=synthetic-session; HttpOnly; SameSite=Strict; Path=/; Secure"],
                    body: stubJSON(["id": "dev_0001", "name": "Test iPhone", "server_version": version]))
            case ("GET", "/api/status"):
                if revoked() {
                    return .init(status: 401, body: stubJSON(["reason": "unauthorized", "message": "x"]))
                }
                return .init(status: 200, body: statusBody)
            default:
                return .init(status: 404, body: stubJSON(["reason": "unknown_route"]))
            }
        }
    }

    func testPairingPostsCodeAndNameAndStoresTheToken() async throws {
        serveDevices()
        let session = session()
        XCTAssertEqual(session.state, .unpaired(reason: nil))

        try await session.pair(payload: payload, name: "  Test iPhone ")

        let request = try XCTUnwrap(DeviceStub.requests.first)
        XCTAssertEqual(request.method, "POST")
        XCTAssertEqual(request.path, "/api/devices/pair")
        XCTAssertNil(request.headers["Authorization"])
        XCTAssertNil(request.headers["Cookie"])
        XCTAssertNil(request.headers["Origin"])
        XCTAssertEqual(request.headers["Content-Type"], "application/json")
        let body = try XCTUnwrap(
            JSONSerialization.jsonObject(with: XCTUnwrap(request.body)) as? [String: String])
        XCTAssertEqual(body, ["code": code, "name": "Test iPhone"])

        let url = URL(string: "https://\(host)")!
        XCTAssertEqual(session.state, .paired(url: url, deviceId: "dev_0001", name: "Test iPhone"))
        XCTAssertEqual(try store.read(), DeviceCredential(url: url, deviceId: "dev_0001", name: "Test iPhone", token: token))
        // The state's description never carries the code; the credential's never the token.
        XCTAssertFalse(DeviceSession.State.pairing(url: url, code: code).description.contains(code))
        XCTAssertFalse(String(describing: try store.read()!).contains(token))
    }

    func testForbiddenLoginExplainsTheTailscaleIdentity() async throws {
        DeviceStub.serve { _ in
            .init(status: 403, body: stubJSON(["reason": "forbidden_login", "message": "x"]))
        }
        let session = session()
        do {
            try await session.pair(payload: payload, name: "Test iPhone")
            XCTFail("pairing should fail")
        } catch let error as DeviceSessionError {
            XCTAssertEqual(error, .refused(DeviceSession.identityExplanation))
        }
        XCTAssertEqual(session.state, .unpaired(reason: DeviceSession.identityExplanation))
        XCTAssertTrue(DeviceSession.identityExplanation.contains("Tailscale"))
        XCTAssertNil(try store.read())
    }

    func testExpiredCodeAndUnreachableMacAreExplained() async throws {
        DeviceStub.serve { _ in
            .init(status: 400, body: stubJSON(["reason": "invalid_pairing_code", "message": "x"]))
        }
        let session = session()
        await XCTAssertThrowsAsync(try await session.pair(payload: payload, name: "Phone"))
        guard case .unpaired(let reason?) = session.state else { return XCTFail("\(session.state)") }
        XCTAssertTrue(reason.contains("expired"))

        DeviceStub.serve { _ in nil }
        await XCTAssertThrowsAsync(try await session.pair(payload: payload, name: "Phone"))
        guard case .unpaired(let offline?) = session.state else { return XCTFail("\(session.state)") }
        XCTAssertTrue(offline.contains("awake and on your tailnet"))
    }

    func testCredentialStoreRoundTripsTheToken() throws {
        let credential = DeviceCredential(
            url: URL(string: "https://\(host)")!, deviceId: "dev_0001", name: "Test iPhone", token: token)
        XCTAssertNil(try store.read())
        try store.write(credential)
        XCTAssertEqual(try store.read(), credential)
        let mode = try FileManager.default.attributesOfItem(atPath: store.url.path)[.posixPermissions] as? Int
        XCTAssertEqual(mode, 0o600)
        // A new session starts paired from the stored credential.
        let restored = session()
        XCTAssertEqual(restored.state, .paired(url: credential.url, deviceId: "dev_0001", name: "Test iPhone"))
        try store.delete()
        XCTAssertNil(try store.read())
        try store.delete()

        let memory = MemoryCredentialStore()
        try memory.write(credential)
        XCTAssertEqual(try memory.read()?.token, token)
    }

    func testLoginSendsTheBearerAndKeepsTheCookie() async throws {
        serveDevices()
        let session = session()
        try await session.pair(payload: payload, name: "Test iPhone")

        let version = try await session.login()

        XCTAssertEqual(version, "2.0.0a1")
        XCTAssertFalse(session.updateAdvised)
        let login = try XCTUnwrap(DeviceStub.requests.last)
        XCTAssertEqual(login.path, "/api/devices/login")
        XCTAssertEqual(login.headers["Authorization"], "Bearer \(token)")
        XCTAssertNil(login.headers["Cookie"])
        XCTAssertEqual(session.cookies.map(\.name), ["fo_session"])

        // Later requests use the cookie, not the bearer.
        _ = try await XCTUnwrap(session.apiClient).status()
        let status = try XCTUnwrap(DeviceStub.requests.last)
        XCTAssertEqual(status.path, "/api/status")
        XCTAssertEqual(status.headers["Cookie"], "fo_session=synthetic-session")
        XCTAssertNil(status.headers["Authorization"])
    }

    func testUnauthorizedAfterRevokeClearsTheTokenAndUnpairs() async throws {
        let revoked = Flag()
        serveDevices(revoked: { revoked.value })
        let session = session()
        try await session.pair(payload: payload, name: "Test iPhone")
        try await session.login()

        revoked.value = true
        do {
            try await session.login()
            XCTFail("login should fail after revoke")
        } catch let error as DeviceSessionError {
            XCTAssertEqual(error, .unpaired(DeviceSession.revokedExplanation))
        }
        XCTAssertEqual(session.state, .unpaired(reason: DeviceSession.revokedExplanation))
        XCTAssertNil(try store.read())
        XCTAssertTrue(session.cookies.isEmpty)
        XCTAssertNil(session.apiClient)

        // Pairing again works cleanly.
        revoked.value = false
        try await session.pair(payload: payload, name: "Test iPhone")
        XCTAssertNotNil(try store.read())
        try await session.login()
    }

    func testUnreachableLoginKeepsThePairing() async throws {
        serveDevices()
        let session = session()
        try await session.pair(payload: payload, name: "Test iPhone")
        DeviceStub.serve { _ in nil }
        do {
            try await session.login()
            XCTFail("login should fail while the Mac is away")
        } catch DeviceSessionError.unreachable(let text) {
            XCTAssertTrue(text.contains("awake"))
        }
        guard case .paired = session.state else { return XCTFail("\(session.state)") }
        XCTAssertNotNil(try store.read())
    }

    func testUnauthorizedFromElsewhereAndUnpair() async throws {
        serveDevices()
        let session = session()
        try await session.pair(payload: payload, name: "Test iPhone")
        session.unauthorized()
        XCTAssertEqual(session.state, .unpaired(reason: DeviceSession.revokedExplanation))
        XCTAssertNil(try store.read())

        try await session.pair(payload: payload, name: "Test iPhone")
        session.unpair()
        XCTAssertEqual(session.state, .unpaired(reason: nil))
        XCTAssertNil(try store.read())
        await XCTAssertThrowsAsync(try await session.login())
    }

    func testNewerServerAdvisesAnUpdate() async throws {
        serveDevices(version: "2.1.0")
        let session = session()
        try await session.pair(payload: payload, name: "Test iPhone")
        try await session.login()
        XCTAssertEqual(session.serverVersion, "2.1.0")
        XCTAssertTrue(session.updateAdvised)

        XCTAssertFalse(DeviceSession.updateAdvised(for: "2.0.0"))
        XCTAssertFalse(DeviceSession.updateAdvised(for: "2.0.9"))
        XCTAssertFalse(DeviceSession.updateAdvised(for: "2.0.0a1"))
        XCTAssertFalse(DeviceSession.updateAdvised(for: "1.9.0"))
        XCTAssertFalse(DeviceSession.updateAdvised(for: nil))
        XCTAssertFalse(DeviceSession.updateAdvised(for: "unknown"))
        XCTAssertTrue(DeviceSession.updateAdvised(for: "2.1.0a2"))
        XCTAssertTrue(DeviceSession.updateAdvised(for: "3.0"))
    }

    func testServerVersionParsing() {
        XCTAssertEqual(ServerVersion("2.0.0a1"), ServerVersion(2, 0, 0))
        XCTAssertEqual(ServerVersion("2.1"), ServerVersion(2, 1, 0))
        XCTAssertEqual(ServerVersion("10.2.3"), ServerVersion(10, 2, 3))
        XCTAssertNil(ServerVersion("v2"))
        XCTAssertLessThan(ServerVersion(2, 0, 9), ServerVersion(2, 1, 0))
    }

    func testManualEntry() throws {
        let typed = try PairingPayload.manual(url: " \(host)/ ", code: "abcd 2345")
        XCTAssertEqual(typed, PairingPayload(url: "https://\(host)", code: "ABCD2345"))
        XCTAssertEqual(
            try PairingPayload.manual(url: "http://localhost:4800/x?y=1", code: "abcd\u{2013}2345"),
            PairingPayload(url: "http://localhost:4800", code: "ABCD2345"))
        XCTAssertThrowsError(try PairingPayload.manual(url: "http://\(host)", code: code))
        XCTAssertThrowsError(try PairingPayload.manual(url: "", code: code))
        XCTAssertThrowsError(try PairingPayload.manual(url: host, code: " - "))
    }

    func testStatusOverTheTailnetCarriesTheIdentity() throws {
        // Over the tailnet /api/status names the Tailscale login; on loopback it is null.
        let body = Data(
            #"{"version": "2.0.0a1", "server_version": "2.0.0a1", "mode": "office", "read_only": false, "chat": true, "remote": true, "identity": {"login": "tester@example.com", "name": "Tester"}, "office": null}"#
                .utf8)
        let status = try APIClient.decode(ServerStatus.self, from: body)
        XCTAssertEqual(status.identity, TailnetIdentity(login: "tester@example.com", name: "Tester"))
    }
}

func stubJSON(_ object: Any) -> Data {
    try! JSONSerialization.data(withJSONObject: object)
}

/// A Bool shared with a stub handler.
final class Flag: @unchecked Sendable {
    private let lock = NSLock()
    private var stored = false
    var value: Bool {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}

@MainActor
func XCTAssertThrowsAsync<T>(
    _ expression: @autoclosure () async throws -> T, file: StaticString = #filePath, line: UInt = #line
) async {
    do {
        _ = try await expression()
        XCTFail("expected an error", file: file, line: line)
    } catch {}
}

@MainActor
final class ReachabilityTimeoutTests: XCTestCase {
    func testUnreachableWithinTheTimeout() async {
        // A probe that never answers in time (a sleeping Mac).
        let reachability = Reachability(timeout: .milliseconds(300)) {
            try? await Task.sleep(for: .seconds(30))
            return true
        }
        let start = ContinuousClock.now
        await reachability.check()
        let elapsed = ContinuousClock.now - start
        XCTAssertFalse(reachability.reachable)
        XCTAssertTrue(reachability.checked)
        XCTAssertNil(reachability.lastSeen)
        XCTAssertLessThan(elapsed, .seconds(2))
        XCTAssertEqual(Reachability.defaultTimeout, .seconds(5))
    }

    func testUnreachableOverHTTPWithinTheTimeout() async {
        // A real loopback port with nothing listening on it.
        let client = APIClient(baseURL: URL(string: "http://127.0.0.1:9")!, timeout: 30)
        let reachability = Reachability(client: client)
        let start = ContinuousClock.now
        await reachability.check()
        XCTAssertFalse(reachability.reachable)
        XCTAssertLessThan(ContinuousClock.now - start, .seconds(6))
    }

    func testLastSeenIsKept() async throws {
        let suite = "fokit-reachability-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        let up = Reachability(defaults: defaults) { true }
        await up.check()
        let seen = try XCTUnwrap(up.lastSeen)

        let relaunched = Reachability(defaults: defaults) { false }
        XCTAssertEqual(relaunched.lastSeen, seen)
        await relaunched.check()
        XCTAssertFalse(relaunched.reachable)
        XCTAssertEqual(relaunched.lastSeen, seen)

        relaunched.forget()
        XCTAssertNil(Reachability(defaults: defaults) { true }.lastSeen)
    }
}
