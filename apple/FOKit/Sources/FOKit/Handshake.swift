import Foundation

/// The one-line JSON handshake `fo serve --app` prints on stdout before anything else.
///
/// `{"port": 4790, "token": "...", "office": "/path/or/null", "state": "ready", "version": "2.0.0"}`
///
/// The token is a per-launch secret: it never appears in `description`, logs or user defaults.
public struct Handshake: Codable, Sendable, Equatable {
    public let port: Int
    public let token: String
    public let office: String?
    public let state: String
    public let version: String

    public init(port: Int, token: String, office: String?, state: String, version: String) {
        self.port = port
        self.token = token
        self.office = office
        self.state = state
        self.version = version
    }

    private enum CodingKeys: String, CodingKey {
        case port, token, office, state, version
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        guard container.contains(.port) else { throw HandshakeError.missingField("port") }
        guard container.contains(.token) else { throw HandshakeError.missingField("token") }
        port = try container.decode(Int.self, forKey: .port)
        token = try container.decode(String.self, forKey: .token)
        office = try container.decodeIfPresent(String.self, forKey: .office)
        // State and version are informational; an older or newer server that omits them
        // still yields a usable handshake.
        state = try container.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        version = try container.decodeIfPresent(String.self, forKey: .version) ?? ""
    }

    /// Parses the first stdout line. Surrounding whitespace is ignored; anything else after
    /// the JSON object is rejected.
    public static func parse(line: String) throws -> Handshake {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{"), let data = trimmed.data(using: .utf8) else {
            throw HandshakeError.notJSON
        }
        let handshake: Handshake
        do {
            handshake = try JSONDecoder().decode(Handshake.self, from: data)
        } catch let error as HandshakeError {
            throw error
        } catch {
            throw HandshakeError.notJSON
        }
        guard (1...65535).contains(handshake.port) else { throw HandshakeError.invalid("port") }
        guard !handshake.token.isEmpty else { throw HandshakeError.invalid("token") }
        return handshake
    }

    /// Fallback for servers without `--app` (before U8 lands): the human-readable
    /// `  Open: http://127.0.0.1:PORT/?t=TOKEN` line `fo serve` prints. Returns nil for any
    /// other line. Remove once every supported server prints the JSON handshake.
    public static func parseOpenLine(_ line: String) -> Handshake? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("Open: "),
            let components = URLComponents(string: String(trimmed.dropFirst("Open: ".count))),
            components.scheme == "http", components.host == "127.0.0.1",
            let port = components.port, (1...65535).contains(port), components.path == "/",
            let token = components.queryItems?.first(where: { $0.name == "t" })?.value,
            !token.isEmpty
        else { return nil }
        return Handshake(port: port, token: token, office: nil, state: "unknown", version: "")
    }

    /// The server's loopback origin.
    public var baseURL: URL {
        URL(string: "http://127.0.0.1:\(port)/")!
    }

    /// The landing URL that sets the session cookie. Only the web view loads it.
    public var landingURL: URL {
        var components = URLComponents(string: "http://127.0.0.1:\(port)/")!
        components.queryItems = [URLQueryItem(name: "t", value: token)]
        return components.url!
    }
}

extension Handshake: CustomStringConvertible, CustomDebugStringConvertible {
    public var description: String {
        "Handshake(port: \(port), office: \(office ?? "none"), state: \(state), version: \(version))"
    }

    public var debugDescription: String { description }
}

public enum HandshakeError: Error, Equatable, Sendable {
    case notJSON
    case missingField(String)
    case invalid(String)
}
