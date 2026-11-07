import Foundation

/// What `tailscale status --json` says about this machine. Only two fields are read:
/// `BackendState` and `Self.DNSName` (the MagicDNS name, without its trailing dot).
public struct TailscaleStatus: Sendable, Equatable {
    /// `Running`, `Stopped`, `NeedsLogin`, `NeedsMachineAuth`, `Starting`, `NoState`, ...
    public let backendState: String
    /// This machine's MagicDNS name, such as `example-mac.tail0000.ts.net`, or nil when
    /// MagicDNS is off or the node is not logged in.
    public let dnsName: String?

    public init(backendState: String, dnsName: String?) {
        self.backendState = backendState
        self.dnsName = dnsName
    }

    public var isRunning: Bool { backendState == "Running" }

    private struct Raw: Decodable {
        struct Node: Decodable {
            let DNSName: String?
        }

        let BackendState: String?
        let selfNode: Node?

        enum CodingKeys: String, CodingKey {
            case BackendState
            case selfNode = "Self"
        }
    }

    public enum ParseError: Error, Equatable, Sendable {
        case notJSON
        case missingBackendState
    }

    public static func parse(_ data: Data) throws -> TailscaleStatus {
        let raw: Raw
        do {
            raw = try JSONDecoder().decode(Raw.self, from: data)
        } catch {
            throw ParseError.notJSON
        }
        guard let state = raw.BackendState, !state.isEmpty else {
            throw ParseError.missingBackendState
        }
        var name = raw.selfNode?.DNSName?.trimmingCharacters(in: .whitespaces) ?? ""
        while name.hasSuffix(".") {
            name.removeLast()
        }
        return TailscaleStatus(backendState: state, dnsName: name.isEmpty ? nil : name)
    }
}

/// The Tailscale states the Devices pane distinguishes.
public enum TailscaleState: Sendable, Equatable {
    case notInstalled
    /// Installed, but not connected (`BackendState` other than `Running`), or its status could
    /// not be read; `detail` says which.
    case stopped(cli: URL, detail: String)
    case running(cli: URL, dnsName: String?)

    public var cli: URL? {
        switch self {
        case .notInstalled: return nil
        case .stopped(let cli, _), .running(let cli, _): return cli
        }
    }
}

public enum Tailscale {
    /// Where the CLI lives, in order: the Mac App Store / standalone app bundle, then the
    /// open-source `tailscaled` installs.
    public static let candidatePaths = [
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        "/usr/local/bin/tailscale",
        "/opt/homebrew/bin/tailscale",
    ]

    public static let downloadURL = URL(string: "https://tailscale.com/download/mac")!

    /// The first executable candidate, or nil when Tailscale is not installed.
    public static func locate(
        isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }
    ) -> URL? {
        candidatePaths.first(where: isExecutable).map { URL(fileURLWithPath: $0) }
    }

    /// Maps a status (or the failure to read one) to the pane's state.
    public static func state(cli: URL, status: Result<TailscaleStatus, Error>) -> TailscaleState {
        switch status {
        case .success(let status) where status.isRunning:
            return .running(cli: cli, dnsName: status.dnsName)
        case .success(let status):
            return .stopped(cli: cli, detail: "Tailscale is \(describe(status.backendState)).")
        case .failure:
            return .stopped(cli: cli, detail: "Tailscale did not report its status.")
        }
    }

    static func describe(_ backendState: String) -> String {
        switch backendState {
        case "Stopped": return "turned off"
        case "NeedsLogin": return "installed but not signed in"
        case "NeedsMachineAuth": return "waiting for this Mac to be approved in the admin console"
        case "Starting": return "starting"
        default: return "not connected (\(backendState))"
        }
    }

    /// `tailscale serve --bg PORT`: HTTPS on the MagicDNS name, proxied to 127.0.0.1:PORT.
    public static func serveArguments(port: Int) -> [String] {
        ["serve", "--bg", String(port)]
    }

    /// Turns off the HTTPS listener `serveArguments` created, leaving any other serve
    /// configuration alone (`tailscale serve reset` would clear all of it).
    public static let stopArguments = ["serve", "--https=443", "off"]

    /// The command a user runs in Terminal to share the server on the tailnet.
    public static func serveCommand(port: Int) -> String {
        "tailscale serve --bg \(port)"
    }

    #if os(macOS)
    /// Runs `tailscale ARGS` with a 10 second timeout.
    public static func run(_ cli: URL, _ arguments: [String], timeout: TimeInterval = 10) async
        -> SubprocessResult
    {
        await Subprocess.run(cli, arguments, timeout: timeout)
    }

    /// Locates the CLI and reads `status --json`.
    public static func detect() async -> TailscaleState {
        guard let cli = locate() else { return .notInstalled }
        let result = await run(cli, ["status", "--json"])
        // `status --json` exits non-zero when stopped but still prints the document.
        if result.launched, !result.timedOut, !result.stdout.isEmpty {
            return state(cli: cli, status: Result { try TailscaleStatus.parse(result.stdout) })
        }
        return state(cli: cli, status: .failure(TailscaleStatus.ParseError.notJSON))
    }
    #endif
}
