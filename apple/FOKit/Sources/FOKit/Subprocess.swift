#if os(macOS)
import Foundation

/// The outcome of one short command. Callers decide what, if anything, to show; nothing here
/// logs the output.
public struct SubprocessResult: Sendable, Equatable {
    /// False when the executable could not be started at all.
    public let launched: Bool
    public let status: Int32
    public let stdout: Data
    public let stderr: Data
    /// True when the command ran past its timeout and was terminated.
    public let timedOut: Bool

    public init(launched: Bool, status: Int32, stdout: Data, stderr: Data, timedOut: Bool) {
        self.launched = launched
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
        self.timedOut = timedOut
    }

    public var succeeded: Bool { launched && !timedOut && status == 0 }
    public var stdoutText: String { String(decoding: stdout, as: UTF8.self) }
    public var stderrText: String { String(decoding: stderr, as: UTF8.self) }
}

/// Runs a command with stdin closed, captures both streams, and terminates it after `timeout`.
public enum Subprocess {
    public static func run(
        _ executable: URL, _ arguments: [String], environment: [String: String]? = nil,
        currentDirectory: URL? = nil, timeout: TimeInterval
    ) async -> SubprocessResult {
        await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            if let environment {
                process.environment = environment
            }
            if let currentDirectory {
                process.currentDirectoryURL = currentDirectory
            }
            process.standardInput = FileHandle.nullDevice
            let out = Pipe()
            let err = Pipe()
            process.standardOutput = out
            process.standardError = err

            let box = OutputBox()
            let group = DispatchGroup()
            group.enter()
            process.terminationHandler = { _ in group.leave() }
            do {
                try process.run()
            } catch {
                process.terminationHandler = nil
                continuation.resume(
                    returning: SubprocessResult(
                        launched: false, status: -1, stdout: Data(), stderr: Data(), timedOut: false))
                return
            }
            // Read both pipes to the end on their own threads so a chatty command never
            // blocks on a full pipe buffer.
            group.enter()
            DispatchQueue.global().async {
                box.setOut(out.fileHandleForReading.readDataToEndOfFile())
                group.leave()
            }
            group.enter()
            DispatchQueue.global().async {
                box.setErr(err.fileHandleForReading.readDataToEndOfFile())
                group.leave()
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
                if process.isRunning {
                    box.markTimedOut()
                    process.terminate()
                }
            }
            group.notify(queue: .global()) {
                continuation.resume(
                    returning: SubprocessResult(
                        launched: true, status: process.terminationStatus, stdout: box.out,
                        stderr: box.err, timedOut: box.timedOut))
            }
        }
    }
}

private final class OutputBox: @unchecked Sendable {
    private let lock = NSLock()
    private var _out = Data()
    private var _err = Data()
    private var _timedOut = false

    var out: Data { lock.withLock { _out } }
    var err: Data { lock.withLock { _err } }
    var timedOut: Bool { lock.withLock { _timedOut } }

    func setOut(_ data: Data) { lock.withLock { _out = data } }
    func setErr(_ data: Data) { lock.withLock { _err = data } }
    func markTimedOut() { lock.withLock { _timedOut = true } }
}
#endif
