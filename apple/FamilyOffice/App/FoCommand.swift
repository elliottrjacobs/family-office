import FOKit
import Foundation

/// The CLI's error envelope, `{"reason": "...", "message": "..."}`, shown under the field
/// that caused it.
struct FoCommandError: Error, Equatable {
    let reason: String
    let message: String

    static let missing = FoCommandError(
        reason: "fo_missing",
        message: "Family Office could not find fo. In development set FO_EXECUTABLE.")
}

/// Runs the same `fo` the server runs, as `fo --json --office PATH ARGS`, with the server's
/// scrubbed environment, and returns its JSON stdout. Settings write `office.toml` only
/// through `fo config set`; the app never edits the file itself.
enum FoCommand {
    static let timeout: TimeInterval = 30

    @MainActor
    static func run(office: String?, _ arguments: [String]) async -> Result<JSONValue, FoCommandError> {
        guard let executable = ServerProcess.resolveExecutable() else { return .failure(.missing) }
        var full = ["--json"]
        if let office {
            full += ["--office", office]
        }
        full += arguments
        let result = await Subprocess.run(
            executable, full,
            environment: ServerProcess.environment(binDirectory: executable.deletingLastPathComponent()),
            currentDirectory: FileManager.default.homeDirectoryForCurrentUser, timeout: timeout)
        return interpret(result)
    }

    /// Success is exit status 0 with a JSON document on stdout; a failure prints the envelope.
    /// Stderr is never shown: the envelope is the CLI's public message.
    static func interpret(_ result: SubprocessResult) -> Result<JSONValue, FoCommandError> {
        guard result.launched else {
            return .failure(FoCommandError(reason: "fo_unavailable", message: "fo could not be started."))
        }
        if result.timedOut {
            return .failure(
                FoCommandError(reason: "timeout", message: "fo did not finish within \(Int(timeout)) seconds."))
        }
        let line = result.stdoutText.split(whereSeparator: \.isNewline).last.map(String.init) ?? ""
        let value = try? JSONDecoder().decode(JSONValue.self, from: Data(line.utf8))
        if result.status == 0, let value {
            return .success(value)
        }
        if case .string(let reason)? = value?["reason"], case .string(let message)? = value?["message"] {
            return .failure(FoCommandError(reason: reason, message: message))
        }
        return .failure(
            FoCommandError(reason: "operation_failed", message: "fo exited with status \(result.status)."))
    }

    /// `fo config get KEY`: the stored value, or nil when the key is unset.
    @MainActor
    static func configGet(office: String?, _ key: String) async -> Result<JSONValue?, FoCommandError> {
        await run(office: office, ["config", "get", key]).map { document in
            if case .bool(false)? = document["set"] { return nil }
            guard let value = document["value"], value != .null else { return nil }
            return value
        }
    }

    /// `fo config set KEY VALUE`: the value as the CLI stored it.
    @MainActor
    static func configSet(office: String?, _ key: String, _ value: String) async -> Result<JSONValue, FoCommandError> {
        await run(office: office, ["config", "set", key, value]).map { $0["value"] ?? .null }
    }
}

extension JSONValue {
    /// The value as a settings field shows it: `4790`, `2.5`, `true`, `name`.
    var fieldText: String {
        switch self {
        case .null: return ""
        case .bool(let value): return value ? "true" : "false"
        case .number(let value):
            if value.rounded() == value, abs(value) < 1e15 { return String(Int64(value)) }
            return String(value)
        case .string(let value): return value
        case .array(let values): return values.map(\.fieldText).joined(separator: ", ")
        case .object: return ""
        }
    }
}
