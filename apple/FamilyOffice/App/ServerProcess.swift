import Darwin
import FOKit
import Foundation

/// Owns the `fo serve --app` child process.
///
/// - Resolves `fo`: the bundled `Contents/Resources/fo/bin/fo`, else `FO_EXECUTABLE`, else the
///   `foExecutablePath` user default (development only). Never a `fo` found on PATH.
/// - Refuses to start when `fo --version` does not contain `FOExpectedVersion` from Info.plist.
/// - Reads the handshake from the first stdout line, then drains stdout and stderr into an
///   in-memory log of the last 500 lines. Nothing is written to disk.
/// - Restarts after an unexpected exit with backoff 1, 2, 4, 8, 8 seconds, five attempts.
@MainActor
final class ServerProcess {
    enum Event {
        case starting
        case handshake(Handshake)
        case restarting(attempt: Int, delay: Int)
        case failed(String)
        case stopped
    }

    static let maxRestarts = 5
    /// A server that stayed up this long is healthy again; its next crash starts the backoff over.
    static let healthyAfter: TimeInterval = 30
    static let handshakeTimeout: Duration = .seconds(30)
    static let stopTimeout: TimeInterval = 5

    /// Development fallback for the executable, read from `UserDefaults`.
    static let executableDefaultsKey = "foExecutablePath"

    var onEvent: ((Event) -> Void)?
    let log = RollingLog(limit: 500)

    private var process: Process?
    private var generation = 0
    private var stopping = false
    private var restarts = 0
    private var startedAt: Date?
    private var office: String?
    private var remote = false
    private var stdoutBuffer = Data()
    private var stderrBuffer = Data()
    private var handshakeReceived = false
    private var sawFirstLine = false
    private var pendingRestart: Task<Void, Never>?
    private var watchdog: Task<Void, Never>?
    /// Executables already checked for version and `fo serve` flags, by path.
    private var checked: [String: ServeFlags] = [:]

    var isRunning: Bool { process?.isRunning ?? false }

    // MARK: - Lifecycle

    /// - Parameter remote: pass `--remote` and let the server take `[serve] port` from
    ///   office.toml (default 4790), so `tailscale serve` can forward to a stable port. Without
    ///   it the app asks for port 0 and the system picks a free loopback port.
    func start(office: String?, remote: Bool = false) {
        pendingRestart?.cancel()
        pendingRestart = nil
        self.office = office
        self.remote = remote
        stopping = false
        restarts = 0
        launch()
    }

    /// SIGTERM, wait up to five seconds, then SIGKILL.
    func stop() async {
        pendingRestart?.cancel()
        pendingRestart = nil
        watchdog?.cancel()
        stopping = true
        guard let process, process.isRunning else {
            self.process = nil
            return
        }
        process.terminate()
        let deadline = Date().addingTimeInterval(Self.stopTimeout)
        while process.isRunning, Date() < deadline {
            try? await Task.sleep(for: .milliseconds(100))
        }
        if process.isRunning {
            kill(process.processIdentifier, SIGKILL)
            log.append("app: server ignored SIGTERM for 5 s; sent SIGKILL")
        }
        self.process = nil
    }

    private func launch() {
        generation += 1
        let current = generation
        onEvent?(.starting)
        guard let executable = Self.resolveExecutable() else {
            onEvent?(
                .failed(
                    "Family Office could not find its server. The bundled runtime is missing; "
                        + "in development set FO_EXECUTABLE to a checkout's .venv/bin/fo."))
            return
        }
        Task {
            let flags: ServeFlags
            if let cached = checked[executable.path] {
                flags = cached
            } else {
                switch await Self.preflight(executable) {
                case .failure(let message):
                    guard current == generation else { return }
                    onEvent?(.failed(message))
                    return
                case .success(let value):
                    flags = value
                    checked[executable.path] = value
                }
            }
            guard current == generation, !stopping else { return }
            spawn(executable, flags: flags, generation: current)
        }
    }

    private func spawn(_ executable: URL, flags: ServeFlags, generation current: Int) {
        let process = Process()
        process.executableURL = executable
        var arguments: [String] = []
        if let office {
            arguments += ["--office", office]
        }
        arguments.append("serve")
        if remote {
            // The configured port, so `tailscale serve --bg PORT` keeps pointing at it.
            arguments.append("--remote")
        } else {
            // Port 0 lets the system pick a free loopback port; the handshake reports it.
            arguments += ["--port", "0"]
        }
        if flags.app {
            arguments.append("--app")
        }
        if flags.parentPid {
            // The server polls this pid and stops itself when the app is gone, so a crash or
            // SIGKILL of the app leaves no server behind.
            arguments += ["--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        }
        process.arguments = arguments
        process.environment = Self.environment(binDirectory: executable.deletingLastPathComponent())
        process.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        process.standardInput = FileHandle.nullDevice
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        stdoutBuffer.removeAll()
        stderrBuffer.removeAll()
        handshakeReceived = false
        sawFirstLine = false

        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            DispatchQueue.main.async {
                MainActor.assumeIsolated { self?.received(data, stderr: false, generation: current) }
            }
        }
        stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            DispatchQueue.main.async {
                MainActor.assumeIsolated { self?.received(data, stderr: true, generation: current) }
            }
        }
        process.terminationHandler = { [weak self] finished in
            let status = finished.terminationStatus
            let reason = finished.terminationReason
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    self?.exited(status: status, signaled: reason == .uncaughtSignal, generation: current)
                }
            }
        }

        do {
            try process.run()
        } catch {
            log.append("app: could not launch the server")
            exited(status: -1, signaled: false, generation: current)
            return
        }
        self.process = process
        startedAt = Date()
        watchdog?.cancel()
        watchdog = Task { [weak self] in
            try? await Task.sleep(for: Self.handshakeTimeout)
            guard !Task.isCancelled, let self, self.generation == current, !self.handshakeReceived
            else { return }
            self.log.append("app: no handshake within 30 s; stopping the server")
            self.process?.terminate()
        }
    }

    // MARK: - Output

    private func received(_ data: Data, stderr: Bool, generation current: Int) {
        guard current == generation else { return }
        if stderr {
            stderrBuffer.append(data)
            for line in Self.takeLines(&stderrBuffer, flush: data.isEmpty) {
                log.append(line)
            }
            return
        }
        stdoutBuffer.append(data)
        for line in Self.takeLines(&stdoutBuffer, flush: data.isEmpty) {
            readStdout(line)
        }
    }

    private func readStdout(_ line: String) {
        if handshakeReceived {
            log.append(line)
            return
        }
        let first = !sawFirstLine
        sawFirstLine = true
        if first, let handshake = try? Handshake.parse(line: line) {
            accept(handshake)
            return
        }
        // Fallback until `fo serve --app` lands everywhere: a first line that is not JSON means
        // no handshake, so take port and token from the printed `Open: http://127.0.0.1:...` line.
        if let handshake = Handshake.parseOpenLine(line) {
            log.redact(handshake.token)
            accept(handshake)
            log.append("app: server printed no JSON handshake; using the Open line")
            return
        }
        log.append(line)
    }

    private func accept(_ handshake: Handshake) {
        handshakeReceived = true
        watchdog?.cancel()
        log.redact(handshake.token)
        onEvent?(.handshake(handshake))
    }

    private static func takeLines(_ buffer: inout Data, flush: Bool) -> [String] {
        var lines: [String] = []
        while let newline = buffer.firstIndex(of: UInt8(ascii: "\n")) {
            let line = buffer[buffer.startIndex..<newline]
            lines.append(String(decoding: line, as: UTF8.self))
            buffer.removeSubrange(buffer.startIndex...newline)
        }
        if flush, !buffer.isEmpty {
            lines.append(String(decoding: buffer, as: UTF8.self))
            buffer.removeAll()
        }
        return lines
    }

    // MARK: - Exit and restart

    private func exited(status: Int32, signaled: Bool, generation current: Int) {
        guard current == generation else { return }
        watchdog?.cancel()
        process = nil
        if stopping {
            onEvent?(.stopped)
            return
        }
        log.append("app: server exited (\(signaled ? "signal" : "status") \(status))")
        if let startedAt, Date().timeIntervalSince(startedAt) >= Self.healthyAfter {
            restarts = 0
        }
        guard restarts < Self.maxRestarts else {
            onEvent?(
                .failed(
                    "The server stopped and could not be restarted after \(Self.maxRestarts) attempts. "
                        + "Use View > Restart Server to try again."))
            return
        }
        restarts += 1
        let delay = min(1 << (restarts - 1), 8)
        onEvent?(.restarting(attempt: restarts, delay: delay))
        pendingRestart = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self, !self.stopping else { return }
            self.launch()
        }
    }

    // MARK: - Executable, environment, preflight

    static func resolveExecutable() -> URL? {
        let fileManager = FileManager.default
        var candidates: [String] = []
        if let resources = Bundle.main.resourceURL {
            candidates.append(resources.appendingPathComponent("fo/bin/fo").path)
        }
        if let path = ProcessInfo.processInfo.environment["FO_EXECUTABLE"], !path.isEmpty {
            candidates.append(path)
        }
        if let path = UserDefaults.standard.string(forKey: executableDefaultsKey), !path.isEmpty {
            candidates.append(path)
        }
        for path in candidates {
            let expanded = (path as NSString).expandingTildeInPath
            if fileManager.isExecutableFile(atPath: expanded) {
                return URL(fileURLWithPath: expanded)
            }
        }
        return nil
    }

    static let passedThrough = [
        "HOME", "USER", "LANG", "TMPDIR",
        "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
    ]

    /// `FO_CLAUDE_EXECUTABLE` and `FO_CODEX_EXECUTABLE`: the CLIs `FOKit.CLIResolver` found,
    /// set by `AppState` before the server starts and whenever detection changes.
    static var engineExecutables: [String: String] = [:]

    /// A scrubbed environment: PATH is the runtime's bin plus /usr/bin:/bin, only the
    /// variables in `passedThrough` survive from the app's own environment, and the engine
    /// CLIs the app found are named in `engineExecutables`.
    static func environment(binDirectory: URL) -> [String: String] {
        let source = ProcessInfo.processInfo.environment
        var environment: [String: String] = [
            "PATH": "\(binDirectory.path):/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
        ]
        for name in passedThrough {
            if let value = source[name], !value.isEmpty {
                environment[name] = value
            }
        }
        if environment["LANG"] == nil {
            environment["LANG"] = "en_US.UTF-8"
        }
        for (name, path) in engineExecutables {
            environment[name] = path
        }
        return environment
    }

    static var expectedVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "FOExpectedVersion") as? String) ?? ""
    }

    /// The optional `fo serve` flags this executable lists in `fo serve --help`.
    struct ServeFlags: Equatable {
        var app: Bool
        var parentPid: Bool

        init(help: String) {
            app = help.contains("--app")
            parentPid = help.contains("--parent-pid")
        }
    }

    enum Preflight {
        case success(ServeFlags)
        case failure(String)
    }

    /// Checks `fo --version` against `FOExpectedVersion` and which optional flags `fo serve`
    /// knows (`--app`, `--parent-pid`).
    static func preflight(_ executable: URL) async -> Preflight {
        let environment = environment(binDirectory: executable.deletingLastPathComponent())
        guard let version = await capture(executable, ["--version"], environment) else {
            return .failure("The server at \(executable.path) did not report its version.")
        }
        let expected = expectedVersion
        guard !expected.isEmpty, version.contains(expected) else {
            let reported = version.trimmingCharacters(in: .whitespacesAndNewlines)
            return .failure(
                "This app expects family-office \(expected), but the server reports "
                    + "\"\(reported)\". Install the matching version or rebuild the app.")
        }
        // Remove with the Open-line fallback once every supported server has `--app` and
        // `--parent-pid`.
        let help = await capture(executable, ["serve", "--help"], environment) ?? ""
        return .success(ServeFlags(help: help))
    }

    /// Runs a short command and returns its stdout, or nil on failure or after 30 seconds.
    nonisolated static func capture(
        _ executable: URL, _ arguments: [String], _ environment: [String: String]
    ) async -> String? {
        await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            process.environment = environment
            process.standardInput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            let pipe = Pipe()
            process.standardOutput = pipe
            process.terminationHandler = { finished in
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let ok = finished.terminationReason == .exit && finished.terminationStatus == 0
                continuation.resume(returning: ok ? String(decoding: data, as: UTF8.self) : nil)
            }
            do {
                try process.run()
            } catch {
                process.terminationHandler = nil
                continuation.resume(returning: nil)
                return
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + 30) {
                if process.isRunning { process.terminate() }
            }
        }
    }
}

/// The last `limit` lines of server output, in memory only, with known tokens redacted.
@MainActor
final class RollingLog {
    private(set) var lines: [String] = []
    private let limit: Int
    private var secrets: [String] = []

    init(limit: Int) {
        self.limit = limit
    }

    /// Masks `secret` in every line appended from now on, and in lines already held.
    func redact(_ secret: String) {
        guard !secret.isEmpty, !secrets.contains(secret) else { return }
        secrets.append(secret)
        lines = lines.map(scrub)
    }

    func append(_ line: String) {
        lines.append(scrub(line))
        if lines.count > limit {
            lines.removeFirst(lines.count - limit)
        }
    }

    private func scrub(_ line: String) -> String {
        var line = line
        for secret in secrets {
            line = line.replacingOccurrences(of: secret, with: "[redacted]")
        }
        // Any landing link, even one printed before its token was known.
        return line.replacingOccurrences(
            of: #"([?&]t=)[^&\s]+"#, with: "$1[redacted]", options: .regularExpression)
    }
}
