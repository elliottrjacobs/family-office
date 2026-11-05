import Foundation
import XCTest

@testable import FOKit

final class EnginesTests: XCTestCase {
    private var root: URL!
    private var home: URL { root.appendingPathComponent("home") }
    private var homebrew: URL { root.appendingPathComponent("opt/homebrew/bin") }
    private var usrLocal: URL { root.appendingPathComponent("usr/local/bin") }
    private var resolver: CLIResolver { CLIResolver(home: home, homebrewBin: homebrew, usrLocalBin: usrLocal) }

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("fokit-engines-\(UUID().uuidString)")
        for directory in [home, homebrew, usrLocal] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    @discardableResult
    private func tool(_ path: URL, executable: Bool = true) throws -> URL {
        try FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/sh\necho 1.0.0\n".utf8).write(to: path)
        try FileManager.default.setAttributes(
            [.posixPermissions: executable ? 0o755 : 0o644], ofItemAtPath: path.path)
        return path
    }

    // MARK: - Resolver

    func testNothingInstalled() {
        XCTAssertNil(resolver.resolve(.claude, loginShellPath: nil))
        XCTAssertNil(resolver.resolve(.codex, loginShellPath: nil))
    }

    func testClaudeAtAnNvmPathAndCodexMissing() throws {
        let claude = try tool(home.appendingPathComponent(".nvm/versions/node/v22.3.0/bin/claude"))
        XCTAssertEqual(resolver.resolve(.claude, loginShellPath: nil), CLILocation(path: claude.path, source: .nvm))
        XCTAssertNil(resolver.resolve(.codex, loginShellPath: nil))
    }

    func testNewestNvmVersionWins() throws {
        try tool(home.appendingPathComponent(".nvm/versions/node/v9.11.2/bin/codex"))
        let newest = try tool(home.appendingPathComponent(".nvm/versions/node/v20.10.0/bin/codex"))
        try tool(home.appendingPathComponent(".nvm/versions/node/v18.19.1/bin/codex"))
        XCTAssertEqual(resolver.resolve(.codex, loginShellPath: nil)?.path, newest.path)
        XCTAssertEqual(resolver.candidates(for: .codex, loginShellPath: nil).count, 3)
    }

    func testResolutionOrder() throws {
        let shell = try tool(root.appendingPathComponent("shell/bin/claude"))
        let nvm = try tool(home.appendingPathComponent(".nvm/versions/node/v22.0.0/bin/claude"))
        let brew = try tool(homebrew.appendingPathComponent("claude"))
        let local = try tool(usrLocal.appendingPathComponent("claude"))
        let localBin = try tool(home.appendingPathComponent(".local/bin/claude"))
        let installer = try tool(home.appendingPathComponent(".claude/local/claude"))
        let candidates = resolver.candidates(for: .claude, loginShellPath: shell.path)
        XCTAssertEqual(candidates.map(\.path), [shell, nvm, brew, local, localBin, installer].map(\.path))
        XCTAssertEqual(
            candidates.map(\.source), [.loginShell, .nvm, .homebrew, .usrLocal, .localBin, .claudeLocal])
    }

    func testClaudeLocalInstallerIsOnlyForClaude() throws {
        try tool(home.appendingPathComponent(".claude/local/codex"))
        XCTAssertNil(resolver.resolve(.codex, loginShellPath: nil))
    }

    func testSkipsNonExecutablesDirectoriesAndRelativeShellAnswers() throws {
        try tool(homebrew.appendingPathComponent("codex"), executable: false)
        try FileManager.default.createDirectory(
            at: usrLocal.appendingPathComponent("codex"), withIntermediateDirectories: true)
        let localBin = try tool(home.appendingPathComponent(".local/bin/codex"))
        XCTAssertEqual(resolver.resolve(.codex, loginShellPath: "codex")?.path, localBin.path)
        XCTAssertEqual(resolver.resolve(.codex, loginShellPath: "/missing/codex")?.path, localBin.path)
    }

    func testDropsASymlinkToACandidateAlreadyFound() throws {
        let real = try tool(homebrew.appendingPathComponent("codex"))
        try FileManager.default.createSymbolicLink(
            at: usrLocal.appendingPathComponent("codex"), withDestinationURL: real)
        let candidates = resolver.candidates(for: .codex, loginShellPath: nil)
        XCTAssertEqual(candidates.map(\.source), [.homebrew])
    }

    func testParsesCommandV() {
        XCTAssertEqual(CLIResolver.parseCommandV("/opt/homebrew/bin/claude\n"), "/opt/homebrew/bin/claude")
        XCTAssertEqual(
            CLIResolver.parseCommandV("Welcome back!\nnvm: using v22\n/home/u/.nvm/bin/claude\n"),
            "/home/u/.nvm/bin/claude")
        XCTAssertNil(CLIResolver.parseCommandV("claude: aliased to npx claude\n"))
        XCTAssertNil(CLIResolver.parseCommandV(""))
    }

    // MARK: - Versions

    func testParsesVersions() {
        XCTAssertEqual(VersionParser.parse("2.1.3 (Claude Code)\n"), "2.1.3")
        XCTAssertEqual(VersionParser.parse("codex-cli 0.50.0"), "0.50.0")
        XCTAssertEqual(VersionParser.parse("v24.1.0"), "24.1.0")
        XCTAssertEqual(VersionParser.parse("tool 1.2"), "1.2")
        XCTAssertEqual(VersionParser.parse("codex-cli 0.51.0-alpha.2"), "0.51.0-alpha.2")
        XCTAssertNil(VersionParser.parse("no version here"))
        XCTAssertNil(VersionParser.parse(""))
    }

    func testComparesVersions() {
        XCTAssertEqual(VersionParser.compare("v20.10.0", "v9.11.2"), .orderedDescending)
        XCTAssertEqual(VersionParser.compare("1.2", "1.2.0"), .orderedSame)
        XCTAssertEqual(VersionParser.compare("1.2.3", "1.10.0"), .orderedAscending)
        XCTAssertEqual(VersionParser.compare("system", "v1.0.0"), .orderedAscending)
    }

    // MARK: - Sign-in

    func testClaudeAuthStatus() {
        XCTAssertEqual(SignInParser.claude(stdout: #"{"loggedIn": true, "authMethod": "x"}"#, status: 0), .signedIn)
        XCTAssertEqual(SignInParser.claude(stdout: #"{"loggedIn": false}"#, status: 1), .signedOut)
        XCTAssertEqual(SignInParser.claude(stdout: "", status: 1), .signedOut)
        if case .unknown = SignInParser.claude(stdout: "hello", status: 0) {} else {
            XCTFail("unrecognized output should be unknown")
        }
    }

    func testClaudeHelpListsAuth() {
        let help = "Commands:\n  config         Manage configuration\n  auth           Manage authentication\n"
        XCTAssertTrue(SignInParser.claudeHasAuthStatus(help: help))
        XCTAssertFalse(SignInParser.claudeHasAuthStatus(help: "Commands:\n  config  Manage\n  --auth-token x\n"))
    }

    func testCodexLoginStatus() {
        XCTAssertEqual(SignInParser.codex(output: "Logged in using ChatGPT\n", status: 0), .signedIn)
        XCTAssertEqual(SignInParser.codex(output: "Not logged in\n", status: 1), .signedOut)
        XCTAssertEqual(SignInParser.codex(output: "", status: 1), .signedOut)
    }

    // MARK: - Server routes

    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
        return try Data(contentsOf: url)
    }

    func testDecodesRunnerStatus() throws {
        let status = try APIClient.decode(RunnerStatus.self, from: fixture("runner"))
        XCTAssertTrue(status.ready)
        XCTAssertEqual(status.engine("claude")?.usable, true)
        XCTAssertEqual(status.engine("codex")?.usable, false)
        XCTAssertEqual(status.engine("codex")?.message, "Install Codex and sign in to chat with advisors.")
        XCTAssertEqual(status.engine("codex")?.defaults?.maxBudgetUsd, 1.5)
    }

    func testDecodesModelCatalog() throws {
        let catalog = try APIClient.decode(ModelCatalog.self, from: fixture("models"))
        XCTAssertEqual(catalog.default, "claude")
        XCTAssertEqual(catalog.engines["claude"]?.models.first?.recommended, true)
        XCTAssertNil(catalog.engines["claude"]?.models.last?.recommended)
        XCTAssertEqual(catalog.defaults["codex"]?.enabled, false)
        XCTAssertEqual(catalog.defaults["codex"]?.model, "custom-model")
    }

    func testInstallGuidanceForBothEngines() {
        for engine in EngineKind.allCases {
            XCTAssertFalse(engine.installCommands.isEmpty)
            XCTAssertTrue(engine.billingNote.contains("your own"))
        }
    }
}
