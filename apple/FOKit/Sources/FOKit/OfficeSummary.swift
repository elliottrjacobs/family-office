import Foundation

/// The one-line texts the Mac menu bar shows, computed from the status, runs and devices
/// routes. Pure functions so the wording is tested without a server.
public enum OfficeSummary {
    /// A phone counts as reachable when the server saw it this recently. The server moves
    /// `last_seen` at most once a minute, so anything under five minutes is "now".
    public static let reachableWithin: TimeInterval = 5 * 60

    /// `Synced 12 min ago`, `Never synced`, or `Setting up` while the server is onboarding.
    public static func syncLine(_ status: ServerStatus?, now: Date = Date()) -> String {
        guard let status else { return "Server not reachable" }
        guard status.mode == "office" else { return "Office not set up yet" }
        guard let last = status.lastSync else { return "Never synced" }
        return "Synced \(relative(from: last, to: now))"
    }

    /// The first run still in progress, newest first as the route lists them.
    public static func activeRun(_ runs: [RunSummary]) -> RunSummary? {
        runs.first(where: \.isActive)
    }

    /// `Run in progress: cio`, or nil when nothing is running.
    public static func runLine(_ runs: [RunSummary]) -> String? {
        activeRun(runs).map { "Run in progress: \($0.skill)" }
    }

    /// `Phone: reachable`, `Phone: last seen 3 h ago`, `Phone: never seen`, or nil when no
    /// phone is paired. With several phones the most recently seen one counts.
    public static func phoneLine(_ devices: [Device], now: Date = Date()) -> String? {
        guard !devices.isEmpty else { return nil }
        let label = devices.count == 1 ? "Phone" : "Phones (\(devices.count))"
        guard let seen = devices.compactMap(\.lastSeenDate).max() else {
            return "\(label): never seen"
        }
        if now.timeIntervalSince(seen) < reachableWithin {
            return "\(label): reachable"
        }
        return "\(label): last seen \(relative(from: seen, to: now))"
    }

    /// `just now`, `12 min ago`, `3 h ago`, `2 d ago`.
    public static func relative(from date: Date, to now: Date) -> String {
        let seconds = max(0, now.timeIntervalSince(date))
        switch seconds {
        case ..<60: return "just now"
        case ..<3600: return "\(Int(seconds / 60)) min ago"
        case ..<86400: return "\(Int(seconds / 3600)) h ago"
        default: return "\(Int(seconds / 86400)) d ago"
        }
    }
}
