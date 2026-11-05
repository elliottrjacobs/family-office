import Foundation
import Security

/// What a paired phone keeps: the server it paired with, the device record the server made,
/// and the device token shown once in the pairing response.
public struct DeviceCredential: Codable, Sendable, Equatable {
    public let url: URL
    public let deviceId: String
    public let name: String
    public let token: String

    public init(url: URL, deviceId: String, name: String, token: String) {
        self.url = url
        self.deviceId = deviceId
        self.name = name
        self.token = token
    }
}

extension DeviceCredential: CustomStringConvertible, CustomDebugStringConvertible {
    /// Never includes the token.
    public var description: String { "DeviceCredential(url: \(url), deviceId: \(deviceId))" }
    public var debugDescription: String { description }
}

/// Where the phone keeps its one credential. The app uses `Keychain`; tests use a stub.
public protocol CredentialStore: Sendable {
    func read() throws -> DeviceCredential?
    func write(_ credential: DeviceCredential) throws
    func delete() throws
}

/// A Keychain failure, carrying only the `OSStatus`.
public struct KeychainError: Error, Equatable, Sendable {
    public let status: OSStatus
}

/// A minimal Security-framework wrapper that keeps the device credential as one generic
/// password item: service `com.familyoffice.phone`, accessible after the first unlock and
/// never migrated to another device or into a backup restored elsewhere.
public struct Keychain: CredentialStore {
    public static let defaultService = "com.familyoffice.phone"

    public let service: String
    public let account: String

    public init(service: String = Keychain.defaultService, account: String = "device") {
        self.service = service
        self.account = account
    }

    private var query: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecUseDataProtectionKeychain as String: true,
        ]
    }

    public func read() throws -> DeviceCredential? {
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else {
            throw KeychainError(status: status)
        }
        // An item this version cannot read is treated as absent; pairing again replaces it.
        return try? JSONDecoder().decode(DeviceCredential.self, from: data)
    }

    public func write(_ credential: DeviceCredential) throws {
        let data = try JSONEncoder().encode(credential)
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var item = query
            item.merge(attributes) { _, new in new }
            status = SecItemAdd(item as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw KeychainError(status: status) }
    }

    public func delete() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError(status: status)
        }
    }
}

/// A credential store in memory, for previews and tests.
public final class MemoryCredentialStore: CredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var credential: DeviceCredential?

    public init(_ credential: DeviceCredential? = nil) {
        self.credential = credential
    }

    public func read() throws -> DeviceCredential? { lock.withLock { credential } }
    public func write(_ credential: DeviceCredential) throws { lock.withLock { self.credential = credential } }
    public func delete() throws { lock.withLock { credential = nil } }
}
