import Foundation
import XCTest

@testable import FOKit

/// Serves canned responses keyed by request path.
final class StubProtocol: URLProtocol, @unchecked Sendable {
    struct Response {
        let status: Int
        let body: Data
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var responses: [String: Response] = [:]
    nonisolated(unsafe) private static var cookieHeaders: [String: String] = [:]
    nonisolated(unsafe) private static var requests: [String: (method: String, origin: String?)] = [:]

    static func set(_ path: String, status: Int = 200, body: Data) {
        lock.withLock { responses[path] = Response(status: status, body: body) }
    }

    static func cookieHeader(for path: String) -> String? {
        lock.withLock { cookieHeaders[path] }
    }

    /// The method and Origin header of the last request to `path`.
    static func request(for path: String) -> (method: String, origin: String?)? {
        lock.withLock { requests[path] }
    }

    static func reset() {
        lock.withLock {
            responses = [:]
            cookieHeaders = [:]
            requests = [:]
        }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path ?? ""
        let response = Self.lock.withLock { () -> Response? in
            Self.cookieHeaders[path] = request.value(forHTTPHeaderField: "Cookie")
            Self.requests[path] = (
                request.httpMethod ?? "GET", request.value(forHTTPHeaderField: "Origin")
            )
            return Self.responses[path]
        }
        guard let response, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let http = HTTPURLResponse(
            url: url, statusCode: response.status, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: response.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class APIClientTests: XCTestCase {
    private let base = URL(string: "http://127.0.0.1:4790/")!

    override func setUp() {
        super.setUp()
        StubProtocol.reset()
    }

    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
        return try Data(contentsOf: url)
    }

    private func client() -> APIClient {
        APIClient(baseURL: base, timeout: 2, protocolClasses: [StubProtocol.self])
    }

    func testDecodesStatus() async throws {
        StubProtocol.set("/api/status", body: try fixture("status"))
        let status = try await client().status()
        XCTAssertEqual(status.version, "2.0.0")
        XCTAssertEqual(status.mode, "office")
        XCTAssertFalse(status.readOnly)
        XCTAssertTrue(status.chat)
        XCTAssertNil(status.identity)
        XCTAssertEqual(status.office?["accounts"], .number(2))
    }

    func testDecodesOnboarding() async throws {
        StubProtocol.set("/api/onboarding", body: try fixture("onboarding"))
        let onboarding = try await client().onboarding()
        XCTAssertEqual(onboarding.state, "never_synced")
        XCTAssertEqual(onboarding.steps.count, 1)
        XCTAssertEqual(onboarding.steps[0].command, "fo sync --office /tmp/example-office")
        XCTAssertEqual(onboarding.providers, [.init(provider: "schwab", connected: true, accounts: 1)])
        XCTAssertEqual(onboarding.doctor.first?["status"], .string("warn"))
        XCTAssertNil(onboarding.lastSync)
    }

    func testDecodesDevices() async throws {
        StubProtocol.set("/api/devices", body: try fixture("devices"))
        let devices = try await client().devices()
        XCTAssertEqual(devices.map(\.id), ["dev_000000000001", "dev_000000000002"])
        XCTAssertEqual(devices[0].lastSeen, "2026-01-02T00:00:00+00:00")
        XCTAssertNil(devices[1].lastSeen)
    }

    func testDecodesRuns() async throws {
        StubProtocol.set("/api/runs", body: try fixture("runs"))
        let runs = try await client().runs()
        XCTAssertEqual(runs.map(\.skill), ["cio", "risk"])
        XCTAssertEqual(runs.map(\.isActive), [true, false])
        XCTAssertEqual(StubProtocol.request(for: "/api/runs")?.method, "GET")
        XCTAssertNil(StubProtocol.request(for: "/api/runs")?.origin)
    }

    func testRequestsPairingCodeWithOrigin() async throws {
        StubProtocol.set("/api/devices/pairing", body: try fixture("pairing"))
        let code = try await client().requestPairingCode()
        XCTAssertEqual(code.code, "ABCD2345")
        XCTAssertEqual(code.expiresDate, Date(timeIntervalSince1970: 1_767_312_300))
        XCTAssertFalse(String(describing: code).contains("ABCD2345"))
        let request = try XCTUnwrap(StubProtocol.request(for: "/api/devices/pairing"))
        XCTAssertEqual(request.method, "POST")
        XCTAssertEqual(request.origin, "http://127.0.0.1:4790")
    }

    func testRevokesDevice() async throws {
        StubProtocol.set(
            "/api/devices/dev_000000000001",
            body: Data(#"{"id": "dev_000000000001", "revoked": true}"#.utf8))
        let result = try await client().revokeDevice(id: "dev_000000000001")
        XCTAssertTrue(result.revoked)
        XCTAssertEqual(StubProtocol.request(for: "/api/devices/dev_000000000001")?.method, "DELETE")
    }

    func testRevokeOfUnknownDeviceCarriesReason() async throws {
        StubProtocol.set(
            "/api/devices/dev_000000000009", status: 404,
            body: Data(#"{"reason": "device_not_found", "message": "No such paired device."}"#.utf8))
        do {
            try await client().revokeDevice(id: "dev_000000000009")
            XCTFail("expected an HTTP error")
        } catch {
            XCTAssertEqual(error as? APIError, .http(status: 404, reason: "device_not_found"))
            XCTAssertEqual(Pairing.explain(error), "That device is no longer paired.")
        }
    }

    func testDecodesServerVersionAndLastSync() throws {
        let body = Data(
            #"{"version": "2.0.0", "server_version": "2.0.0", "mode": "office", "read_only": false, "chat": true, "remote": false, "identity": null, "office": {"last_sync": {"as_of": "2026-01-02T03:04:05+00:00"}}}"#
                .utf8)
        let status = try APIClient.decode(ServerStatus.self, from: body)
        XCTAssertEqual(status.serverVersion, "2.0.0")
        XCTAssertEqual(status.lastSync, Date(timeIntervalSince1970: 1_767_323_045))
    }

    func testDecodingFailureIsTyped() async throws {
        StubProtocol.set("/api/status", body: try fixture("status-missing-mode"))
        do {
            _ = try await client().status()
            XCTFail("expected a decoding error")
        } catch let error as APIError {
            XCTAssertEqual(error, .decoding(type: "ServerStatus", detail: "missing mode"))
        }
    }

    func testHTTPErrorCarriesServerReason() async throws {
        StubProtocol.set(
            "/api/status", status: 401,
            body: Data(#"{"reason": "no_session", "message": "Open the link again."}"#.utf8))
        do {
            _ = try await client().status()
            XCTFail("expected an HTTP error")
        } catch let error as APIError {
            XCTAssertEqual(error, .http(status: 401, reason: "no_session"))
        }
    }

    func testTransportFailureIsTyped() async throws {
        do {
            _ = try await client().status()
            XCTFail("expected a transport error")
        } catch let error as APIError {
            guard case .transport = error else { return XCTFail("got \(error)") }
        }
    }

    func testSendsCopiedSessionCookieOnly() async throws {
        StubProtocol.set("/api/status", body: try fixture("status"))
        let api = client()
        let session = HTTPCookie(properties: [
            .domain: "127.0.0.1", .path: "/", .name: "fo_session", .value: "constant-cookie",
        ])!
        let foreign = HTTPCookie(properties: [
            .domain: "example.com", .path: "/", .name: "other", .value: "x",
        ])!
        api.setCookies([session, foreign])
        XCTAssertTrue(api.hasSessionCookie)
        _ = try await api.status()
        XCTAssertEqual(StubProtocol.cookieHeader(for: "/api/status"), "fo_session=constant-cookie")
    }

    @MainActor
    func testReachabilityPublishesState() async {
        let up = Reachability { true }
        await up.check()
        XCTAssertTrue(up.reachable)
        XCTAssertNotNil(up.lastSeen)

        let down = Reachability { false }
        await down.check()
        XCTAssertFalse(down.reachable)
        XCTAssertNil(down.lastSeen)
    }
}
