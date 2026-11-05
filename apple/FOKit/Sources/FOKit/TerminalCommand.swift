import Foundation

/// Exit statuses from the terminal's process.
public enum WaitStatus {
    /// SwiftTerm's forkpty path reports the raw `waitpid` status. Returns the exit code for
    /// a normal exit, `-signal` for a process killed by a signal.
    public static func exitCode(raw: Int32) -> Int32 {
        let signal = raw & 0x7F
        return signal == 0 ? (raw >> 8) & 0xFF : -signal
    }
}

/// The only `fo` commands the embedded terminal runs (plan R30): `setup`, `auth <provider>`,
/// `sync` and `doctor`. Anything else is refused here, before a process exists, and the
/// terminal never starts a shell.
public enum TerminalCommand: Sendable, Equatable, Identifiable {
    /// `fo --office PATH setup PATH [--provider P]`: creates the office and connects accounts.
    case setup(provider: String?)
    /// `fo --office PATH auth PROVIDER`: the CLI's hidden prompts and, for Schwab, the
    /// browser consent page.
    case auth(String)
    case sync
    case doctor

    /// Providers `fo auth` connects in the terminal. Key-based providers use native fields
    /// and `fo connect` instead.
    public static let authProviders = ["schwab", "simplefin"]

    public var id: String { words.joined(separator: " ") }

    /// Parses `["auth", "schwab"]` and the like; nil for anything outside the allowed set.
    public init?(_ words: [String]) {
        switch words {
        case ["setup"]:
            self = .setup(provider: nil)
        case let w where w.count == 3 && w[0] == "setup" && w[1] == "--provider"
            && Self.authProviders.contains(w[2]):
            self = .setup(provider: w[2])
        case let w where w.count == 2 && w[0] == "auth" && Self.authProviders.contains(w[1]):
            self = .auth(w[1])
        case ["sync"]:
            self = .sync
        case ["doctor"]:
            self = .doctor
        default:
            return nil
        }
    }

    /// The subcommand words, without the office.
    public var words: [String] {
        switch self {
        case .setup(let provider?): return ["setup", "--provider", provider]
        case .setup(nil): return ["setup"]
        case .auth(let provider): return ["auth", provider]
        case .sync: return ["sync"]
        case .doctor: return ["doctor"]
        }
    }

    /// The full argument vector after the executable, with `--office PATH` first. `setup`
    /// also takes the office as its path argument. Returns nil when the command is not in
    /// the allowed set (always false for a value built through this type, but checked again
    /// so a future case cannot slip through) or the office path is empty.
    public func arguments(office: String) -> [String]? {
        guard !office.isEmpty, TerminalCommand(words) == self else { return nil }
        switch self {
        case .setup(let provider):
            var arguments = ["--office", office, "setup", office]
            if let provider { arguments += ["--provider", provider] }
            return arguments
        default:
            return ["--office", office] + words
        }
    }

    public var title: String {
        switch self {
        case .setup: return "Set up the office"
        case .auth(let provider): return "Connect \(provider == "schwab" ? "Schwab" : provider == "simplefin" ? "SimpleFIN" : provider)"
        case .sync: return "Sync accounts"
        case .doctor: return "Check the office"
        }
    }

    /// One sentence on what will happen, shown above the terminal.
    public var explanation: String {
        switch self {
        case .auth("schwab"):
            return
                "fo auth schwab asks for your Schwab app key and secret (typing stays hidden) and "
                + "the registered callback URL, then opens Schwab's consent page in your browser; "
                + "after you approve there, it finishes here on its own."
        case .auth("simplefin"):
            return
                "fo auth simplefin asks for a SimpleFIN setup token (typing stays hidden) and "
                + "exchanges it for an access link stored in the office's secrets folder."
        case .auth(let provider):
            return "fo auth \(provider) asks for its credentials; typing stays hidden."
        case .setup:
            return "fo setup creates the office and asks for each account's credentials."
        case .sync:
            return "fo sync refreshes every connected account."
        case .doctor:
            return "fo doctor checks the office and reports what needs attention."
        }
    }
}
