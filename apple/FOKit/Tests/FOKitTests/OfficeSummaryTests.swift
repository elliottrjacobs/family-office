import Foundation
import XCTest

@testable import FOKit

/// The menu bar's status lines.
final class OfficeSummaryTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_767_323_045)  // 2026-01-02T03:04:05Z

    private func status(mode: String = "office", lastSync: String?) throws -> ServerStatus {
        let sync = lastSync.map { #"{"as_of": "\#($0)"}"# } ?? "null"
        let body = #"{"version": "2.0.0", "mode": "\#(mode)", "read_only": false, "chat": true, "remote": false, "office": {"last_sync": \#(sync)}}"#
        return try APIClient.decode(ServerStatus.self, from: Data(body.utf8))
    }

    func testSyncLine() throws {
        XCTAssertEqual(OfficeSummary.syncLine(nil, now: now), "Server not reachable")
        XCTAssertEqual(OfficeSummary.syncLine(try status(mode: "onboarding", lastSync: nil), now: now), "Office not set up yet")
        XCTAssertEqual(OfficeSummary.syncLine(try status(lastSync: nil), now: now), "Never synced")
        XCTAssertEqual(
            OfficeSummary.syncLine(try status(lastSync: "2026-01-02T02:52:05+00:00"), now: now),
            "Synced 12 min ago")
        XCTAssertEqual(
            OfficeSummary.syncLine(try status(lastSync: "2026-01-01T03:04:04.500000+00:00"), now: now),
            "Synced 1 d ago")
    }

    func testRunLine() {
        let done = RunSummary(id: "1", skill: "risk", subject: nil, status: "completed", created: nil)
        let live = RunSummary(id: "2", skill: "cio", subject: nil, status: "verifying", created: nil)
        XCTAssertNil(OfficeSummary.runLine([]))
        XCTAssertNil(OfficeSummary.runLine([done]))
        XCTAssertEqual(OfficeSummary.runLine([done, live]), "Run in progress: cio")
    }

    func testPhoneLine() {
        func device(_ seen: String?) -> Device {
            Device(id: "dev_000000000001", name: "Example Phone", created: "2026-01-01T00:00:00+00:00", lastSeen: seen)
        }
        XCTAssertNil(OfficeSummary.phoneLine([], now: now))
        XCTAssertEqual(OfficeSummary.phoneLine([device(nil)], now: now), "Phone: never seen")
        XCTAssertEqual(OfficeSummary.phoneLine([device("2026-01-02T03:02:05+00:00")], now: now), "Phone: reachable")
        XCTAssertEqual(
            OfficeSummary.phoneLine([device("2026-01-02T00:04:05+00:00")], now: now), "Phone: last seen 3 h ago")
        XCTAssertEqual(
            OfficeSummary.phoneLine([device(nil), device("2026-01-02T03:04:00+00:00")], now: now),
            "Phones (2): reachable")
    }

    func testRelative() {
        XCTAssertEqual(OfficeSummary.relative(from: now, to: now), "just now")
        XCTAssertEqual(OfficeSummary.relative(from: now.addingTimeInterval(30), to: now), "just now")
        XCTAssertEqual(OfficeSummary.relative(from: now.addingTimeInterval(-59 * 60), to: now), "59 min ago")
        XCTAssertEqual(OfficeSummary.relative(from: now.addingTimeInterval(-2 * 86400), to: now), "2 d ago")
    }
}
