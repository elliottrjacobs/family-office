import Foundation
import Observation

/// Polls the server's status route and publishes whether it answered, and when it last did.
///
/// Each probe gets at most `timeout` (five seconds by default): a server that does not answer
/// in time counts as unreachable, so a sleeping Mac shows as such within that time.
/// `lastSeen` can be kept in `UserDefaults` so the phone still says when it last reached the
/// Mac after a relaunch.
@MainActor
@Observable
public final class Reachability {
    public static let defaultTimeout: Duration = .seconds(5)

    public private(set) var reachable = false
    /// True once at least one probe has finished.
    public private(set) var checked = false
    public private(set) var lastSeen: Date?

    private let probe: @Sendable () async -> Bool
    private let interval: Duration
    private let timeout: Duration
    private let defaults: UserDefaults?
    private let lastSeenKey: String
    private var task: Task<Void, Never>?

    /// - Parameters:
    ///   - interval: time between probes.
    ///   - timeout: how long one probe may take before it counts as unreachable.
    ///   - defaults: where `lastSeen` is kept; nil keeps it in memory only.
    ///   - lastSeenKey: the defaults key for `lastSeen`.
    ///   - probe: returns true when the server answered.
    public init(
        interval: Duration = .seconds(5),
        timeout: Duration = Reachability.defaultTimeout,
        defaults: UserDefaults? = nil,
        lastSeenKey: String = "lastSeen",
        probe: @escaping @Sendable () async -> Bool
    ) {
        self.interval = interval
        self.timeout = timeout
        self.defaults = defaults
        self.lastSeenKey = lastSeenKey
        self.probe = probe
        self.lastSeen = defaults?.object(forKey: lastSeenKey) as? Date
    }

    /// Probes `GET /api/status` through `client`. Any HTTP answer, even a 401 or a body this
    /// build cannot decode, means the server is up.
    public convenience init(
        client: APIClient,
        interval: Duration = .seconds(5),
        timeout: Duration = Reachability.defaultTimeout,
        defaults: UserDefaults? = nil,
        lastSeenKey: String = "lastSeen"
    ) {
        self.init(
            interval: interval, timeout: timeout, defaults: defaults, lastSeenKey: lastSeenKey
        ) {
            do {
                _ = try await client.status()
                return true
            } catch APIError.http, APIError.decoding {
                return true
            } catch {
                return false
            }
        }
    }

    public func start() {
        guard task == nil else { return }
        task = Task { [weak self] in
            while !Task.isCancelled {
                await self?.check()
                guard let interval = self?.interval else { return }
                try? await Task.sleep(for: interval)
            }
        }
    }

    public func stop() {
        task?.cancel()
        task = nil
    }

    /// Runs one probe now, giving up after the timeout.
    public func check() async {
        let answered = await Self.race(probe, timeout: timeout)
        reachable = answered
        checked = true
        if answered {
            let now = Date()
            lastSeen = now
            defaults?.set(now, forKey: lastSeenKey)
        }
    }

    /// Forgets `lastSeen` (after unpairing).
    public func forget() {
        lastSeen = nil
        reachable = false
        checked = false
        defaults?.removeObject(forKey: lastSeenKey)
    }

    /// The probe's answer, or false when the timeout passes first. Returns at the timeout even
    /// when the probe ignores cancellation; the probe is cancelled and its late answer dropped.
    nonisolated static func race(_ probe: @escaping @Sendable () async -> Bool, timeout: Duration)
        async -> Bool
    {
        let once = Once()
        return await withCheckedContinuation { continuation in
            let work = Task {
                let answer = await probe()
                if once.claim() { continuation.resume(returning: answer) }
            }
            Task {
                try? await Task.sleep(for: timeout)
                if once.claim() {
                    work.cancel()
                    continuation.resume(returning: false)
                }
            }
        }
    }
}

/// A flag that can be claimed once, from any thread.
private final class Once: @unchecked Sendable {
    private let lock = NSLock()
    private var claimed = false

    func claim() -> Bool {
        lock.withLock {
            defer { claimed = true }
            return !claimed
        }
    }
}
