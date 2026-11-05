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

/// One paired phone in `GET /api/devices`.
public struct Device: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let created: String
    public let lastSeen: String?

    private enum CodingKeys: String, CodingKey {
        case id, name, created
        case lastSeen = "last_seen"
    }
}

/// `GET /api/devices` returns `{"devices": [...]}`.
public struct DeviceList: Codable, Sendable, Equatable {
    public let devices: [Device]
}
