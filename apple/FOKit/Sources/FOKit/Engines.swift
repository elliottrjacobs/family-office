import Foundation

/// The advisor engines the app can detect: Claude Code and Codex.
///
/// Detection only reports what is on this Mac. The server finds `claude` and `codex` on its
/// own PATH when it runs an advisor; the app never installs, updates or signs in an engine.
public enum EngineKind: String, CaseIterable, Sendable, Identifiable {
    case claude
    case codex

    public var id: String { rawValue }

    /// The command-line tool's file name.
    public var cli: String { rawValue }

    public var label: String {
        switch self {
        case .claude: return "Claude Code"
        case .codex: return "Codex"
        }
    }

    /// The official install commands, in the order the vendor documents them.
    public var installCommands: [String] {
        switch self {
        case .claude:
            return [
                "curl -fsSL https://claude.ai/install.sh | bash",
                "brew install --cask claude-code",
                "npm install -g @anthropic-ai/claude-code",
            ]
        case .codex:
            return [
                "npm install -g @openai/codex",
                "brew install --cask codex",
            ]
        }
    }

    /// The command that signs in, run by the user in their own terminal.
    public var signInCommand: String {
        switch self {
        case .claude: return "claude"
        case .codex: return "codex login"
        }
    }

    public var installGuide: URL {
        switch self {
        case .claude: return URL(string: "https://code.claude.com/docs/en/setup")!
        case .codex: return URL(string: "https://learn.chatgpt.com/docs/codex/cli")!
        }
    }

    public var billingNote: String {
        switch self {
        case .claude:
            return "Advisor runs bill through your own Claude subscription or Anthropic API account."
        case .codex:
            return "Advisor runs bill through your own ChatGPT plan or OpenAI API account."
        }
    }
}

/// Where a CLI was found, in the order the resolver tries them.
public enum CLISource: String, Sendable, Equatable {
    /// `command -v` in the user's login shell.
    case loginShell = "login shell"
    /// `~/.nvm/versions/node/*/bin`, newest Node first.
    case nvm = "nvm"
    case homebrew = "Homebrew"
    case usrLocal = "/usr/local/bin"
    case localBin = "~/.local/bin"
    /// Claude Code's own local installer, `~/.claude/local/claude`.
    case claudeLocal = "Claude Code local install"
}

public struct CLILocation: Sendable, Equatable {
    public let path: String
    public let source: CLISource

    public init(path: String, source: CLISource) {
        self.path = path
        self.source = source
    }

    public var url: URL { URL(fileURLWithPath: path) }
}

/// Finds an engine CLI without relying on the app's own PATH, which for a Finder-launched app
/// is only `/usr/bin:/bin:/usr/sbin:/sbin`.
public struct CLIResolver: Sendable {
    public let home: URL
    public let homebrewBin: URL
    public let usrLocalBin: URL

    public init(
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        homebrewBin: URL = URL(fileURLWithPath: "/opt/homebrew/bin"),
        usrLocalBin: URL = URL(fileURLWithPath: "/usr/local/bin")
    ) {
        self.home = home
        self.homebrewBin = homebrewBin
        self.usrLocalBin = usrLocalBin
    }

    /// Every executable candidate, in resolution order: the login shell's answer, nvm (newest
    /// Node version first), Homebrew, `/usr/local/bin`, `~/.local/bin`, and for Claude Code
    /// `~/.claude/local/claude`. Duplicates (by resolved path) are dropped.
    public func candidates(for engine: EngineKind, loginShellPath: String?) -> [CLILocation] {
        var found: [CLILocation] = []
        var seen: Set<String> = []
        func consider(_ path: String, _ source: CLISource) {
            guard path.hasPrefix("/"), Self.isExecutableFile(path) else { return }
            let resolved = URL(fileURLWithPath: path).resolvingSymlinksInPath().path
            guard seen.insert(resolved).inserted else { return }
            found.append(CLILocation(path: path, source: source))
        }
        if let loginShellPath {
            consider(loginShellPath, .loginShell)
        }
        for directory in nvmBinDirectories() {
            consider(directory.appendingPathComponent(engine.cli).path, .nvm)
        }
        consider(homebrewBin.appendingPathComponent(engine.cli).path, .homebrew)
        consider(usrLocalBin.appendingPathComponent(engine.cli).path, .usrLocal)
        consider(home.appendingPathComponent(".local/bin/\(engine.cli)").path, .localBin)
        if engine == .claude {
            consider(home.appendingPathComponent(".claude/local/claude").path, .claudeLocal)
        }
        return found
    }

    /// The first candidate, or nil when the CLI is not installed anywhere the app looks.
    public func resolve(_ engine: EngineKind, loginShellPath: String?) -> CLILocation? {
        candidates(for: engine, loginShellPath: loginShellPath).first
    }

    /// `~/.nvm/versions/node/<version>/bin`, newest version first.
    func nvmBinDirectories() -> [URL] {
        let root = home.appendingPathComponent(".nvm/versions/node")
        let names = (try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []
        return
            names
            .filter { !$0.hasPrefix(".") }
            .sorted { VersionParser.compare($0, $1) == .orderedDescending }
            .map { root.appendingPathComponent($0).appendingPathComponent("bin") }
    }

    static func isExecutableFile(_ path: String) -> Bool {
        var directory: ObjCBool = false
        let fileManager = FileManager.default
        return fileManager.fileExists(atPath: path, isDirectory: &directory) && !directory.boolValue
            && fileManager.isExecutableFile(atPath: path)
    }

    /// The last line of `command -v` output that is an absolute path. A login shell's profile
    /// may print other text first, and `command -v` names aliases and functions without a path.
    public static func parseCommandV(_ output: String) -> String? {
        output
            .split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .last { $0.hasPrefix("/") && !$0.contains(" ") }
    }
}

/// Version strings from `--version` output.
public enum VersionParser {
    /// The first `MAJOR.MINOR[.PATCH][-pre]` in `text`: `2.1.3 (Claude Code)` gives `2.1.3`,
    /// `codex-cli 0.50.0` gives `0.50.0`, `v24.1.0` gives `24.1.0`.
    public static func parse(_ text: String) -> String? {
        let pattern = #"(?<![\d.])(\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.]+)?)"#
        guard let range = text.range(of: pattern, options: .regularExpression) else { return nil }
        return String(text[range])
    }

    /// Numeric components of a version, ignoring a leading `v` and any pre-release suffix.
    public static func components(_ version: String) -> [Int] {
        guard let parsed = parse(version) else { return [] }
        let core = parsed.split(separator: "-", maxSplits: 1).first ?? ""
        return core.split(separator: ".").compactMap { Int($0) }
    }

    /// Compares two version strings numerically; unparseable strings sort first.
    public static func compare(_ lhs: String, _ rhs: String) -> ComparisonResult {
        let left = components(lhs)
        let right = components(rhs)
        for index in 0..<max(left.count, right.count) {
            let a = index < left.count ? left[index] : 0
            let b = index < right.count ? right[index] : 0
            if a != b { return a < b ? .orderedAscending : .orderedDescending }
        }
        if left.isEmpty != right.isEmpty { return left.isEmpty ? .orderedAscending : .orderedDescending }
        return .orderedSame
    }
}

/// Whether an engine CLI reports a signed-in account. Only the yes or no is kept: account
/// names and emails in the CLI's output are never stored, shown or logged.
public enum SignInState: Sendable, Equatable {
    case signedIn
    case signedOut
    /// The CLI offers no status check this app understands; `reason` says why.
    case unknown(String)

    public var label: String {
        switch self {
        case .signedIn: return "Signed in"
        case .signedOut: return "Not signed in"
        case .unknown(let reason): return "Unknown (\(reason))"
        }
    }
}

public enum SignInParser {
    /// Whether `claude --help` lists the `auth` command, so `claude auth status` exists.
    public static func claudeHasAuthStatus(help: String) -> Bool {
        help.split(whereSeparator: \.isNewline).contains { line in
            let words = line.split(separator: " ", omittingEmptySubsequences: true)
            return words.first == "auth"
        }
    }

    /// `claude auth status` prints JSON with `loggedIn`; it exits 1 when signed out.
    public static func claude(stdout: String, status: Int32) -> SignInState {
        if let data = stdout.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let loggedIn = object["loggedIn"] as? Bool
        {
            return loggedIn ? .signedIn : .signedOut
        }
        return status == 0 ? .unknown("unrecognized status output") : .signedOut
    }

    /// `codex login status` prints `Logged in using …` (exit 0) or `Not logged in` (exit 1),
    /// on stdout or stderr depending on the version.
    public static func codex(output: String, status: Int32) -> SignInState {
        let text = output.lowercased()
        if text.contains("not logged in") { return .signedOut }
        if text.contains("logged in") { return status == 0 ? .signedIn : .signedOut }
        return status == 0 ? .unknown("unrecognized status output") : .signedOut
    }
}

/// What the app found for one engine on this Mac.
public struct EngineDetection: Sendable, Equatable {
    public let engine: EngineKind
    public let location: CLILocation?
    /// Parsed from `--version`; nil when the CLI did not answer in time.
    public let version: String?
    public let signIn: SignInState

    public init(engine: EngineKind, location: CLILocation?, version: String?, signIn: SignInState) {
        self.engine = engine
        self.location = location
        self.version = version
        self.signIn = signIn
    }

    public var installed: Bool { location != nil }
}

#if os(macOS)
/// Runs the detection: the login shell lookup, the path resolver, `--version` and the
/// sign-in check, each with a timeout.
public struct EngineDetector: Sendable {
    public static let timeout: TimeInterval = 10

    public let resolver: CLIResolver
    /// Variables passed through to the CLIs from the app's environment: the ones that decide
    /// which account and configuration a CLI reads.
    public let passedThrough: [String]

    public init(
        resolver: CLIResolver = CLIResolver(),
        passedThrough: [String] = [
            "HOME", "USER", "LANG", "TMPDIR",
            "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
        ]
    ) {
        self.resolver = resolver
        self.passedThrough = passedThrough
    }

    public func detect(_ engine: EngineKind) async -> EngineDetection {
        let shellPath = await loginShellLookup(engine.cli)
        guard let location = resolver.resolve(engine, loginShellPath: shellPath) else {
            return EngineDetection(engine: engine, location: nil, version: nil, signIn: .signedOut)
        }
        let environment = environment(for: location)
        let versionRun = await Subprocess.run(
            location.url, ["--version"], environment: environment,
            currentDirectory: resolver.home, timeout: Self.timeout)
        let version = versionRun.succeeded ? VersionParser.parse(versionRun.stdoutText) : nil
        let signIn = await signInState(engine, location, environment)
        return EngineDetection(engine: engine, location: location, version: version, signIn: signIn)
    }

    func signInState(
        _ engine: EngineKind, _ location: CLILocation, _ environment: [String: String]
    ) async -> SignInState {
        switch engine {
        case .claude:
            let help = await Subprocess.run(
                location.url, ["--help"], environment: environment,
                currentDirectory: resolver.home, timeout: Self.timeout)
            guard help.succeeded, SignInParser.claudeHasAuthStatus(help: help.stdoutText) else {
                return .unknown("this version has no auth status command")
            }
            let status = await Subprocess.run(
                location.url, ["auth", "status"], environment: environment,
                currentDirectory: resolver.home, timeout: Self.timeout)
            guard status.launched, !status.timedOut else { return .unknown("no answer") }
            return SignInParser.claude(stdout: status.stdoutText, status: status.status)
        case .codex:
            let status = await Subprocess.run(
                location.url, ["login", "status"], environment: environment,
                currentDirectory: resolver.home, timeout: Self.timeout)
            guard status.launched, !status.timedOut else { return .unknown("no answer") }
            return SignInParser.codex(
                output: status.stdoutText + "\n" + status.stderrText, status: status.status)
        }
    }

    /// The CLI's own directory first, so an nvm or Homebrew install finds its `node`.
    func environment(for location: CLILocation) -> [String: String] {
        let source = ProcessInfo.processInfo.environment
        let directory = location.url.deletingLastPathComponent().path
        var environment = [
            "PATH": "\(directory):\(resolver.homebrewBin.path):\(resolver.usrLocalBin.path):/usr/bin:/bin"
        ]
        for name in passedThrough {
            if let value = source[name], !value.isEmpty {
                environment[name] = value
            }
        }
        environment["HOME"] = environment["HOME"] ?? resolver.home.path
        environment["NO_COLOR"] = "1"
        return environment
    }

    /// `/bin/zsh -lc 'command -v <cli>'`: the PATH the user's login shell builds.
    func loginShellLookup(_ cli: String) async -> String? {
        guard cli.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "-" }) else { return nil }
        let source = ProcessInfo.processInfo.environment
        var environment = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin"]
        for name in ["HOME", "USER", "LANG", "TMPDIR"] {
            if let value = source[name], !value.isEmpty {
                environment[name] = value
            }
        }
        let result = await Subprocess.run(
            URL(fileURLWithPath: "/bin/zsh"), ["-lc", "command -v \(cli)"], environment: environment,
            currentDirectory: resolver.home, timeout: 5)
        guard result.succeeded else { return nil }
        return CLIResolver.parseCommandV(result.stdoutText)
    }
}
#endif

/// One engine in `GET /api/runner`.
public struct RunnerEngine: Codable, Sendable, Equatable {
    public let name: String
    public let usable: Bool
    public let version: String?
    public let reason: String?
    public let message: String?
    public let defaults: EngineDefaults?
}

/// `[serve.engines.<name>]` as the server resolved it.
public struct EngineDefaults: Codable, Sendable, Equatable {
    public let model: String
    public let effort: String
    public let maxBudgetUsd: Double
    public let enabled: Bool

    public init(model: String, effort: String, maxBudgetUsd: Double, enabled: Bool) {
        self.model = model
        self.effort = effort
        self.maxBudgetUsd = maxBudgetUsd
        self.enabled = enabled
    }

    private enum CodingKeys: String, CodingKey {
        case model, effort, enabled
        case maxBudgetUsd = "max_budget_usd"
    }
}

/// `GET /api/runner`: every engine, usable or why not.
public struct RunnerStatus: Codable, Sendable, Equatable {
    public let ready: Bool
    public let `default`: String
    public let engines: [RunnerEngine]
    public let message: String?

    public func engine(_ name: String) -> RunnerEngine? {
        engines.first { $0.name == name }
    }
}

/// `GET /api/models`: the curated models per engine and the office's defaults.
public struct ModelCatalog: Codable, Sendable, Equatable {
    public struct Model: Codable, Sendable, Equatable, Identifiable {
        public let id: String
        public let label: String
        public let recommended: Bool?
    }

    public struct Engine: Codable, Sendable, Equatable {
        public let label: String
        public let efforts: [String]
        public let models: [Model]
    }

    public let engines: [String: Engine]
    public let `default`: String
    public let defaults: [String: EngineDefaults]
}
