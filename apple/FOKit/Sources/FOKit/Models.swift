import Foundation

/// Any JSON value, for the parts of a response the apps show but do not interpret.
public enum JSONValue: Codable, Sendable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    public subscript(key: String) -> JSONValue? {
        if case .object(let object) = self { return object[key] }
        return nil
    }
}

/// `GET /api/status`.
public struct ServerStatus: Codable, Sendable, Equatable {
    public let version: String
    /// The package version of the server; older servers omit it and send only `version`.
    public let serverVersion: String?
    public let mode: String
    public let readOnly: Bool
    public let chat: Bool
    public let remote: Bool
    public let identity: String?
    /// The office status document, or nil while onboarding.
    public let office: JSONValue?

    private enum CodingKeys: String, CodingKey {
        case version, mode, chat, remote, identity, office
        case readOnly = "read_only"
        case serverVersion = "server_version"
    }

    /// When the last sync finished: `office.last_sync.as_of`, or nil when never synced.
    public var lastSync: Date? {
        guard case .string(let stamp)? = office?["last_sync"]?["as_of"] else { return nil }
        return ISODate.parse(stamp)
    }
}

/// `GET /api/onboarding`: the state machine the setup flow follows.
public struct Onboarding: Codable, Sendable, Equatable {
    public struct Step: Codable, Sendable, Equatable {
        public let command: String
        public let purpose: String
    }

    public struct Provider: Codable, Sendable, Equatable {
        public let provider: String
        public let connected: Bool
        public let accounts: Int
    }

    public let state: String
    public let reason: String
    public let office: String?
    public let candidate: String?
    public let steps: [Step]
    public let note: String?
    public let providers: [Provider]
    public let doctor: [JSONValue]
    public let lastSync: String?

    private enum CodingKeys: String, CodingKey {
        case state, reason, office, candidate, steps, note, providers, doctor
        case lastSync = "last_sync"
    }
}

/// One paired phone in `GET /api/devices`: `{"id", "name", "created", "last_seen"}`.
public struct Device: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    /// When the phone paired, ISO 8601.
    public let created: String
    /// The last authenticated request, ISO 8601; the server moves it at most once a minute.
    public let lastSeen: String?

    public init(id: String, name: String, created: String, lastSeen: String?) {
        self.id = id
        self.name = name
        self.created = created
        self.lastSeen = lastSeen
    }

    private enum CodingKeys: String, CodingKey {
        case id, name, created
        case lastSeen = "last_seen"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        name = try container.decodeIfPresent(String.self, forKey: .name) ?? "Unnamed device"
        created = try container.decodeIfPresent(String.self, forKey: .created) ?? ""
        lastSeen = try container.decodeIfPresent(String.self, forKey: .lastSeen)
    }

    public var createdDate: Date? { ISODate.parse(created) }
    public var lastSeenDate: Date? { lastSeen.flatMap(ISODate.parse) }
}

/// `GET /api/devices` returns `{"devices": [...]}`.
public struct DeviceList: Codable, Sendable, Equatable {
    public let devices: [Device]
}

/// `DELETE /api/devices/{id}` returns `{"id": ..., "revoked": true}`.
public struct DeviceRevocation: Codable, Sendable, Equatable {
    public let id: String
    public let revoked: Bool
}

/// `POST /api/devices/pairing` returns `{"code": "ABCD2345", "expires_at": "...+00:00"}`.
/// The code is single use and valid five minutes; the app shows it on screen and nowhere else.
public struct PairingCode: Codable, Sendable, Equatable {
    public let code: String
    public let expiresAt: String

    public init(code: String, expiresAt: String) {
        self.code = code
        self.expiresAt = expiresAt
    }

    private enum CodingKeys: String, CodingKey {
        case code
        case expiresAt = "expires_at"
    }

    public var expiresDate: Date? { ISODate.parse(expiresAt) }
}

extension PairingCode: CustomStringConvertible, CustomDebugStringConvertible {
    // Keeps the code out of logs and test failure output.
    public var description: String { "PairingCode(expires_at: \(expiresAt))" }
    public var debugDescription: String { description }
}

/// One advisor run in `GET /api/runs` (a JSON array, newest first). Only the fields the apps
/// show are decoded.
public struct RunSummary: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let skill: String
    public let subject: String?
    public let status: String
    public let created: String?

    public init(id: String, skill: String, subject: String?, status: String, created: String?) {
        self.id = id
        self.skill = skill
        self.subject = subject
        self.status = status
        self.created = created
    }

    /// The statuses the server counts as in progress.
    public static let activeStatuses: Set<String> = ["queued", "running", "verifying"]

    public var isActive: Bool { Self.activeStatuses.contains(status) }
}

/// ISO 8601 timestamps as the server writes them (`isoformat`, with or without fractions).
public enum ISODate {
    public static func parse(_ text: String) -> Date? {
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let date = plain.date(from: text) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: text)
    }
}
