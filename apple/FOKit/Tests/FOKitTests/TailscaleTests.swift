import Foundation
import XCTest

@testable import FOKit

/// The `tailscale status --json` parser, against constant fixtures with example names only.
final class TailscaleTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
        return try Data(contentsOf: url)
    }

    private let cli = URL(fileURLWithPath: "/Applications/Tailscale.app/Contents/MacOS/Tailscale")

    func testParsesRunningStatusAndStripsTrailingDot() throws {
        let status = try TailscaleStatus.parse(try fixture("tailscale-status"))
        XCTAssertEqual(status.backendState, "Running")
        XCTAssertEqual(status.dnsName, "example-mac.tail0000.ts.net")
        XCTAssertTrue(status.isRunning)
        XCTAssertEqual(
            Tailscale.state(cli: cli, status: .success(status)),
            .running(cli: cli, dnsName: "example-mac.tail0000.ts.net"))
    }

    func testParsesStoppedStatusWithoutName() throws {
        let status = try TailscaleStatus.parse(try fixture("tailscale-status-stopped"))
        XCTAssertEqual(status.backendState, "Stopped")
        XCTAssertNil(status.dnsName)
        XCTAssertFalse(status.isRunning)
        XCTAssertEqual(
            Tailscale.state(cli: cli, status: .success(status)),
            .stopped(cli: cli, detail: "Tailscale is turned off."))
    }

    func testNeedsLoginIsExplained() throws {
        let status = try TailscaleStatus.parse(Data(#"{"BackendState": "NeedsLogin", "Self": null}"#.utf8))
        guard case .stopped(_, let detail) = Tailscale.state(cli: cli, status: .success(status)) else {
            return XCTFail("expected stopped")
        }
        XCTAssertEqual(detail, "Tailscale is installed but not signed in.")
    }

    func testRejectsOutputThatIsNotStatus() {
        XCTAssertThrowsError(try TailscaleStatus.parse(Data("not json".utf8))) { error in
            XCTAssertEqual(error as? TailscaleStatus.ParseError, .notJSON)
        }
        XCTAssertThrowsError(try TailscaleStatus.parse(Data(#"{"Self": {}}"#.utf8))) { error in
            XCTAssertEqual(error as? TailscaleStatus.ParseError, .missingBackendState)
        }
    }

    func testLocatesTheFirstInstalledCandidate() {
        XCTAssertNil(Tailscale.locate(isExecutable: { _ in false }))
        XCTAssertEqual(
            Tailscale.locate(isExecutable: { $0 == "/opt/homebrew/bin/tailscale" })?.path,
            "/opt/homebrew/bin/tailscale")
        XCTAssertEqual(
            Tailscale.locate(isExecutable: { _ in true })?.path,
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    }

    func testServeCommands() {
        XCTAssertEqual(Tailscale.serveArguments(port: 4790), ["serve", "--bg", "4790"])
        XCTAssertEqual(Tailscale.stopArguments, ["serve", "--https=443", "off"])
        XCTAssertEqual(Tailscale.serveCommand(port: 4790), "tailscale serve --bg 4790")
    }
}
