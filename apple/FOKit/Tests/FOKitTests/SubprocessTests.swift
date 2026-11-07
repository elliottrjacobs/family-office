import Foundation
import XCTest

@testable import FOKit

final class SubprocessTests: XCTestCase {
    func testCapturesBothStreamsAndStatus() async {
        let result = await Subprocess.run(
            URL(fileURLWithPath: "/bin/sh"), ["-c", "echo out; echo err >&2; exit 3"], timeout: 10)
        XCTAssertTrue(result.launched)
        XCTAssertFalse(result.timedOut)
        XCTAssertEqual(result.status, 3)
        XCTAssertEqual(result.stdoutText, "out\n")
        XCTAssertEqual(result.stderrText, "err\n")
        XCTAssertFalse(result.succeeded)
    }

    func testTerminatesAfterTimeout() async {
        let started = Date()
        let result = await Subprocess.run(URL(fileURLWithPath: "/bin/sleep"), ["30"], timeout: 0.5)
        XCTAssertTrue(result.timedOut)
        XCTAssertLessThan(Date().timeIntervalSince(started), 10)
    }

    func testWritesStdinAndClosesIt() async {
        let result = await Subprocess.run(
            URL(fileURLWithPath: "/bin/cat"), [], stdin: Data("synthetic-input".utf8), timeout: 10)
        XCTAssertTrue(result.succeeded)
        XCTAssertEqual(result.stdoutText, "synthetic-input")
    }

    func testStdinToACommandThatDoesNotReadIt() async {
        let result = await Subprocess.run(
            URL(fileURLWithPath: "/usr/bin/true"), [], stdin: Data(count: 1 << 20), timeout: 10)
        XCTAssertTrue(result.succeeded)
    }

    func testReportsAMissingExecutable() async {
        let result = await Subprocess.run(URL(fileURLWithPath: "/nonexistent/tool"), [], timeout: 1)
        XCTAssertFalse(result.launched)
    }
}
