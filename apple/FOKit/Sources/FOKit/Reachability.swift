import Foundation
import Observation

/// Polls the server's status route and publishes whether it answered, and when it last did.
@MainActor
@Observable
public final class Reachability {
    public private(set) var reachable = false
    public private(set) var lastSeen: Date?

    private let probe: @Sendable () async -> Bool
    private let interval: Duration
    private var task: Task<Void, Never>?

    /// - Parameters:
    ///   - interval: time between probes.
    ///   - probe: returns true when the server answered.
    public init(interval: Duration = .seconds(5), probe: @escaping @Sendable () async -> Bool) {
        self.interval = interval
        self.probe = probe
    }

    /// Probes `GET /api/status` through a client whose timeout should be short (a few seconds).
    /// Any HTTP answer, even a 401, means the server is up.
    public convenience init(client: APIClient, interval: Duration = .seconds(5)) {
        self.init(interval: interval) {
            do {
                _ = try await client.status()
                return true
            } catch APIError.http {
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

    /// Runs one probe now.
    public func check() async {
        let answered = await probe()
        reachable = answered
        if answered {
            lastSeen = Date()
        }
    }
}
