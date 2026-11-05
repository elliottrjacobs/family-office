import XCTest

@testable import FOKit

final class TerminalCommandTests: XCTestCase {
    let office = "/tmp/synthetic-office"

    func testAcceptsOnlyTheFourCommands() {
        XCTAssertEqual(TerminalCommand(["setup"]), .setup(provider: nil))
        XCTAssertEqual(TerminalCommand(["setup", "--provider", "schwab"]), .setup(provider: "schwab"))
        XCTAssertEqual(TerminalCommand(["auth", "schwab"]), .auth("schwab"))
        XCTAssertEqual(TerminalCommand(["auth", "simplefin"]), .auth("simplefin"))
        XCTAssertEqual(TerminalCommand(["sync"]), .sync)
        XCTAssertEqual(TerminalCommand(["doctor"]), .doctor)
    }

    func testRefusesEverythingElse() {
        let refused: [[String]] = [
            [], ["bash"], ["/bin/zsh"], ["serve"], ["connect", "exa"], ["config", "set", "x", "y"],
            ["auth"], ["auth", "alphavantage"], ["auth", "schwab", "--extra"], ["auth", "../schwab"],
            ["sync", "--office", "/elsewhere"], ["doctor", "--notify"], ["setup", "/other/path"],
            ["setup", "--provider", "csv"], ["--office", "/x", "sync"], ["sh", "-c", "fo sync"],
        ]
        for words in refused {
            XCTAssertNil(TerminalCommand(words), "\(words) should be refused")
        }
    }

    func testOfficeComesFirst() {
        XCTAssertEqual(TerminalCommand.auth("schwab").arguments(office: office), ["--office", office, "auth", "schwab"])
        XCTAssertEqual(TerminalCommand.sync.arguments(office: office), ["--office", office, "sync"])
        XCTAssertEqual(TerminalCommand.doctor.arguments(office: office), ["--office", office, "doctor"])
        XCTAssertEqual(
            TerminalCommand.setup(provider: "simplefin").arguments(office: office),
            ["--office", office, "setup", office, "--provider", "simplefin"])
    }

    func testAValueBuiltOutsideTheParserIsStillChecked() {
        XCTAssertNil(TerminalCommand.auth("fred").arguments(office: office))
        XCTAssertNil(TerminalCommand.setup(provider: "csv").arguments(office: office))
        XCTAssertNil(TerminalCommand.sync.arguments(office: ""))
    }

    func testSchwabExplainsTheBrowserConsent() {
        XCTAssertTrue(TerminalCommand.auth("schwab").explanation.contains("browser"))
        XCTAssertTrue(TerminalCommand.auth("simplefin").explanation.contains("hidden"))
    }

    func testWaitStatus() {
        XCTAssertEqual(WaitStatus.exitCode(raw: 0), 0)
        XCTAssertEqual(WaitStatus.exitCode(raw: 1 << 8), 1)
        XCTAssertEqual(WaitStatus.exitCode(raw: 2 << 8), 2)
        XCTAssertEqual(WaitStatus.exitCode(raw: 15), -15)
    }
}
