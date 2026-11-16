import XCTest

@testable import FOKit

final class TerminalCommandTests: XCTestCase {
    let office = "/tmp/synthetic-office"

    func testAcceptsOnlyTheFourCommands() {
        XCTAssertEqual(TerminalCommand(["setup"]), .setup(provider: nil))
        XCTAssertEqual(TerminalCommand(["setup", "--offline"]), .setupOffline)
        XCTAssertEqual(TerminalCommand(["auth", "simplefin"]), .auth("simplefin"))
        XCTAssertEqual(TerminalCommand(["auth", "plaid"]), .auth("plaid"))
        XCTAssertEqual(TerminalCommand(["setup", "--provider", "plaid"]), .setup(provider: "plaid"))
        XCTAssertEqual(TerminalCommand(["sync"]), .sync)
        XCTAssertEqual(TerminalCommand(["doctor"]), .doctor)
    }

    func testRefusesEverythingElse() {
        let refused: [[String]] = [
            [], ["bash"], ["/bin/zsh"], ["serve"], ["connect", "exa"], ["config", "set", "x", "y"],
            ["auth"], ["auth", "alphavantage"], ["auth", "schwab"], ["auth", "simplefin", "--extra"], ["auth", "../plaid"], ["auth", "plaid", "--extra"],
            ["sync", "--office", "/elsewhere"], ["doctor", "--notify"], ["setup", "/other/path"],
            ["setup", "--provider", "csv"], ["--office", "/x", "sync"], ["sh", "-c", "fo sync"],
            ["setup", "--provider", "schwab"], ["setup", "--offline", "--provider", "plaid"], ["setup", "--offline", "/other/path"],
        ]
        for words in refused {
            XCTAssertNil(TerminalCommand(words), "\(words) should be refused")
        }
    }

    func testOfficeComesFirst() {
        XCTAssertEqual(TerminalCommand.auth("plaid").arguments(office: office), ["--office", office, "auth", "plaid"])
        XCTAssertEqual(TerminalCommand.sync.arguments(office: office), ["--office", office, "sync"])
        XCTAssertEqual(TerminalCommand.doctor.arguments(office: office), ["--office", office, "doctor"])
        XCTAssertEqual(
            TerminalCommand.setup(provider: "simplefin").arguments(office: office),
            ["--office", office, "setup", office, "--provider", "simplefin"])
        XCTAssertEqual(
            TerminalCommand.setupOffline.arguments(office: office),
            ["--office", office, "setup", office, "--offline"])
    }

    func testAValueBuiltOutsideTheParserIsStillChecked() {
        XCTAssertNil(TerminalCommand.auth("fred").arguments(office: office))
        XCTAssertNil(TerminalCommand.setup(provider: "csv").arguments(office: office))
        XCTAssertNil(TerminalCommand.sync.arguments(office: ""))
    }

    func testSimpleFINExplainsTheHiddenToken() {
        XCTAssertTrue(TerminalCommand.auth("simplefin").explanation.contains("hidden"))
    }

    func testPlaidExplainsOwnCredentialsAndLink() {
        let text = TerminalCommand.auth("plaid").explanation
        XCTAssertTrue(text.contains("your own Plaid client ID and secret"))
        XCTAssertTrue(text.contains("Plaid Link"))
        XCTAssertEqual(TerminalCommand.auth("plaid").title, "Connect Plaid")
        XCTAssertEqual(TerminalCommand.auth("simplefin").title, "Connect SimpleFIN")
    }

    func testWaitStatus() {
        XCTAssertEqual(WaitStatus.exitCode(raw: 0), 0)
        XCTAssertEqual(WaitStatus.exitCode(raw: 1 << 8), 1)
        XCTAssertEqual(WaitStatus.exitCode(raw: 2 << 8), 2)
        XCTAssertEqual(WaitStatus.exitCode(raw: 15), -15)
    }
}
