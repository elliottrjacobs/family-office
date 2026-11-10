import FOKit
import Foundation
import Observation

/// The phone's app state on top of `DeviceSession`: whether the paired Mac is connected,
/// being reached, or away, plus a reachability loop while the app is in front.
@MainActor
@Observable
final class PhoneModel {
    enum Phase: Equatable {
        /// Not paired, or paired and not tried yet.
        case idle
        case connecting
        /// Logged in; the web view has the session cookie.
        case connected
        /// Paired but not connected, with what went wrong if known.
        case offline(String?)
    }

    let session: DeviceSession
    private(set) var phase: Phase = .idle
    private(set) var reachability: Reachability?
    /// Changes whenever the web view should reload.
    private(set) var reloadToken = 0

    private var loop: Task<Void, Never>?
    private static let lastSeenKey = "lastSeen"
    private static let interval: Duration = .seconds(10)

    init(session: DeviceSession) {
        self.session = session
        if case .paired(let url, _, _) = session.state {
            reachability = makeReachability(for: url)
        }
    }

    var reachable: Bool { reachability?.reachable ?? false }
    var lastSeen: Date? { reachability?.lastSeen }

    /// `example-mac` for `https://example-mac.tail0000.ts.net`; the whole host for a bare name.
    static func macName(for url: URL) -> String {
        let host = url.host ?? url.absoluteString
        return host.split(separator: ".").first.map(String.init) ?? host
    }

    // MARK: Lifecycle

    /// The app came to the front: log in when needed and start probing.
    func resume() {
        guard case .paired = session.state else { return }
        if phase != .connected && phase != .connecting {
            Task { await connect() }
        }
        startLoop()
    }

    func suspend() {
        loop?.cancel()
        loop = nil
    }

    // MARK: Pairing and login

    func pair(payload: PairingPayload, name: String) async throws {
        try await session.pair(payload: payload, name: name)
        if case .paired(let url, _, _) = session.state {
            reachability = makeReachability(for: url)
        }
        await connect()
        startLoop()
    }

    /// Trades the device token for a session; a 401 lands on pairing with the reason.
    func connect() async {
        guard case .paired = session.state, phase != .connecting else { return }
        phase = .connecting
        do {
            try await session.login()
            await reachability?.check()
            phase = .connected
            reload()
        } catch DeviceSessionError.unpaired {
            stopAfterUnpairing()
        } catch let error as DeviceSessionError {
            await reachability?.check()
            phase = .offline(error.message)
        } catch {
            phase = .offline(nil)
        }
    }

    func retry() {
        Task { await connect() }
    }

    func reload() {
        reloadToken += 1
    }

    /// A cookie 401 may mean the Mac restarted; authenticate with the stored token again.
    func sessionExpired() {
        guard phase != .connecting else { return }
        Task { await connect() }
    }

    /// Forgets the pairing on this phone only.
    func unpair() {
        session.unpair()
        stopAfterUnpairing()
    }

    private func stopAfterUnpairing() {
        suspend()
        reachability?.forget()
        reachability = nil
        phase = .idle
    }

    // MARK: Reachability

    private func makeReachability(for url: URL) -> Reachability {
        Reachability(defaults: .standard, lastSeenKey: Self.lastSeenKey) { [weak self] in
            await self?.probe() ?? false
        }
    }

    /// `GET /api/status` with the session cookie when there is one. Any HTTP answer (even one
    /// this build cannot decode) means the Mac is up; a 401 while holding a session cookie
    /// means the session needs a fresh login.
    private func probe() async -> Bool {
        guard let client = session.apiClient else { return false }
        do {
            _ = try await client.status()
            return true
        } catch APIError.http(401, _) {
            if client.hasSessionCookie {
                sessionExpired()
            }
            return true
        } catch APIError.http, APIError.decoding {
            return true
        } catch {
            return false
        }
    }

    private func startLoop() {
        guard loop == nil, reachability != nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: Self.interval)
                guard let self, !Task.isCancelled else { return }
                await self.tick()
            }
        }
    }

    private func tick() async {
        guard let reachability, case .paired = session.state else { return }
        await reachability.check()
        switch phase {
        case .connected where !reachability.reachable:
            phase = .offline(nil)
        case .offline where reachability.reachable, .idle where reachability.reachable:
            await connect()
        default:
            break
        }
    }
}
