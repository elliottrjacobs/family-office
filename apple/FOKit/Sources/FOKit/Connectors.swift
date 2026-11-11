import Foundation

/// How a provider is connected.
public enum ConnectorKind: String, Sendable, Equatable {
    /// An account provider: `fo auth <provider>` in the embedded terminal.
    case account
    /// An API key: a native field whose value goes to `fo connect <provider>` on stdin.
    case key
    /// SEC EDGAR: a contact string, `fo connect edgar --user-agent "Name email"`.
    case contact
}

public struct Connector: Sendable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let kind: ConnectorKind
    /// What the office uses it for.
    public let purpose: String
    /// Where to get a key or account, shown as a link.
    public let signUp: URL?
}

/// The providers the Connectors pane lists, in display order. Provider ids match
/// `fo connect` and `fo auth`.
public enum ConnectorCatalog {
    public static let all: [Connector] = [
        Connector(
            id: "schwab", label: "Schwab", kind: .account,
            purpose: "Brokerage positions, lots and transactions.",
            signUp: URL(string: "https://developer.schwab.com")),
        Connector(
            id: "simplefin", label: "SimpleFIN", kind: .account,
            purpose: "Bank and card balances and transactions.",
            signUp: URL(string: "https://beta-bridge.simplefin.org")),
        Connector(
            id: "alphavantage", label: "Alpha Vantage", kind: .key,
            purpose: "Quotes and price history.",
            signUp: URL(string: "https://www.alphavantage.co/support/#api-key")),
        Connector(
            id: "fred", label: "FRED", kind: .key,
            purpose: "Economic data series for macro reads.",
            signUp: URL(string: "https://fred.stlouisfed.org/docs/api/api_key.html")),
        Connector(
            id: "exa", label: "Exa", kind: .key,
            purpose: "Web search for research runs.",
            signUp: URL(string: "https://dashboard.exa.ai")),
        Connector(
            id: "firecrawl", label: "Firecrawl", kind: .key,
            purpose: "Fetching web pages as text for research runs.",
            signUp: URL(string: "https://www.firecrawl.dev")),
        Connector(
            id: "gemini", label: "Gemini", kind: .key,
            purpose: "Gemini Deep Research for long research tasks.",
            signUp: URL(string: "https://aistudio.google.com/apikey")),
        Connector(
            id: "edgar", label: "SEC EDGAR", kind: .contact,
            purpose: "Company filings. The SEC asks every client to send a name and email.",
            signUp: nil),
    ]

    public static func connector(_ id: String) -> Connector? {
        all.first { $0.id == id }
    }

    public static func label(_ id: String) -> String {
        connector(id)?.label ?? id
    }
}

/// A provider's connection state as the pane shows it.
public enum ConnectionState: Sendable, Equatable {
    case connected
    case notConnected
    /// The server's routes could not be read, so nothing is known beyond this session.
    case notReported

    public var label: String {
        switch self {
        case .connected: return "Connected"
        case .notConnected: return "Not connected"
        case .notReported: return "Not reported by the server"
        }
    }
}

/// The outcome of the last Save or Remove in this session. Holds the CLI's message, never
/// the key.
public struct ConnectOutcome: Sendable, Equatable {
    public let connected: Bool
    public let succeeded: Bool
    public let message: String

    public init(connected: Bool, succeeded: Bool, message: String) {
        self.connected = connected
        self.succeeded = succeeded
        self.message = message
    }
}

/// Connection states from the server's routes. Swift never reads the per-machine
/// credentials folder outside the office:
/// - account providers: `GET /api/onboarding` `providers[].connected`, else a masked entry in
///   `GET /api/config` `secrets` (from `keys.toml` in that folder);
/// - key providers: the last Save or Remove in this session, else a masked `secrets` entry
///   (the route lists `keys.toml` entries and the `<provider>.json` files in that folder
///   `fo connect` writes, as `{"<provider>": {"api_key": "***"}}`), else not connected; not
///   reported only while the config route has not answered;
/// - EDGAR: `settings.providers.edgar.user_agent` in `GET /api/config`.
public struct ConnectorStates: Sendable, Equatable {
    public var onboarding: [Onboarding.Provider]
    /// `GET /api/config`: `{"settings": {...}, "secrets": {"provider": {...masked}}}`.
    public var config: JSONValue?
    public var outcomes: [String: ConnectOutcome]

    public init(
        onboarding: [Onboarding.Provider] = [], config: JSONValue? = nil,
        outcomes: [String: ConnectOutcome] = [:]
    ) {
        self.onboarding = onboarding
        self.config = config
        self.outcomes = outcomes
    }

    func hasMaskedSecret(_ id: String) -> Bool {
        guard case .object(let secrets)? = config?["secrets"], let entry = secrets[id] else {
            return false
        }
        if case .object(let fields) = entry { return !fields.isEmpty }
        return entry != .null
    }

    /// The stored EDGAR contact, `Name email@example.com`, or nil.
    public var edgarUserAgent: String? {
        guard case .string(let value)? = config?["settings"]?["providers"]?["edgar"]?["user_agent"],
            !value.isEmpty
        else { return nil }
        return value
    }

    public func state(_ connector: Connector) -> ConnectionState {
        switch connector.kind {
        case .account:
            if let outcome = outcomes[connector.id], outcome.succeeded {
                return outcome.connected ? .connected : .notConnected
            }
            if let provider = onboarding.first(where: { $0.provider == connector.id }) {
                return provider.connected ? .connected : .notConnected
            }
            return hasMaskedSecret(connector.id) ? .connected : .notConnected
        case .key:
            if let outcome = outcomes[connector.id], outcome.succeeded {
                return outcome.connected ? .connected : .notConnected
            }
            if hasMaskedSecret(connector.id) { return .connected }
            return config == nil ? .notReported : .notConnected
        case .contact:
            if let outcome = outcomes[connector.id], outcome.succeeded {
                return outcome.connected ? .connected : .notConnected
            }
            if config == nil { return .notReported }
            return edgarUserAgent == nil ? .notConnected : .connected
        }
    }
}

/// The `fo connect` invocations the pane makes. The key itself is never an argument: it is
/// the `stdin` of the save invocation.
public enum ConnectCommand {
    public static let keyProviders = ConnectorCatalog.all.filter { $0.kind == .key }.map(\.id)

    /// `fo connect <provider>`, with the key on stdin.
    public static func save(_ provider: String) -> [String]? {
        keyProviders.contains(provider) ? ["connect", provider] : nil
    }

    /// `fo connect --remove <provider>`.
    public static func remove(_ provider: String) -> [String]? {
        guard let connector = ConnectorCatalog.connector(provider), connector.kind != .account else {
            return nil
        }
        return ["connect", "--remove", provider]
    }

    /// `fo connect edgar --user-agent "Name email"`.
    public static func edgar(name: String, email: String) -> [String] {
        ["connect", "edgar", "--user-agent", edgarUserAgent(name: name, email: email)]
    }

    public static func edgarUserAgent(name: String, email: String) -> String {
        let name = name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let email = email.trimmingCharacters(in: .whitespacesAndNewlines)
        return "\(name) \(email)"
    }

    /// The bytes written to `fo connect`'s stdin: the trimmed key and a newline, or nil when
    /// the field holds nothing `fo connect` could accept (empty, whitespace inside, longer
    /// than 512 characters, or unprintable), so an obvious slip never leaves the app.
    public static func stdin(forKey raw: String) -> Data? {
        let key = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty, key.count <= 512,
            key.unicodeScalars.allSatisfy({ $0.value > 0x20 && $0.value != 0x7F })
        else { return nil }
        return Data((key + "\n").utf8)
    }
}
