import FOKit
import Foundation
import Observation
import os

/// Polls the status, runs and devices routes every thirty seconds for the menu bar, the
/// Devices pane and the keep-awake assertion. Each route fails on its own: a server without
/// chat still reports status and devices.
@MainActor
@Observable
final class OfficeMonitor {
    static let interval: Duration = .seconds(30)

    private(set) var status: ServerStatus?
    private(set) var runs: [RunSummary] = []
    /// Nil until the devices route has answered once for the current server.
    private(set) var devices: [Device]?
    private(set) var lastUpdate: Date?

    /// Called whenever a devices answer arrives, with the new list.
    @ObservationIgnored var onDevices: (([Device]) -> Void)?

    @ObservationIgnored private var api: APIClient?
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private let log = Logger(subsystem: "com.familyoffice.app", category: "monitor")

    /// Starts polling through `api`, or stops and clears everything when it is nil.
    func attach(_ api: APIClient?) {
        if api === self.api, task != nil { return }
        task?.cancel()
        task = nil
        self.api = api
        guard api != nil else {
            status = nil
            runs = []
            return
        }
        task = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(for: Self.interval)
            }
        }
    }

    func stop() {
        attach(nil)
    }

    /// Polls all three routes now.
    func refresh() async {
        guard let api else { return }
        async let status = api.status()
        async let runs = api.runs()
        async let devices = api.devices()

        let statusResult = try? await status
        let runsResult = try? await runs
        let devicesResult = try? await devices
        guard api === self.api else { return }

        self.status = statusResult
        self.runs = runsResult ?? []
        if let list = devicesResult {
            self.devices = list
            onDevices?(list)
        }
        lastUpdate = Date()
        // Counts and modes only: never tokens, codes, names or paths.
        log.info(
            "poll status=\(self.status?.mode ?? "unreachable", privacy: .public) runs=\(self.runs.count, privacy: .public) active=\(OfficeSummary.activeRun(self.runs) != nil, privacy: .public) devices=\(self.devices.map { String($0.count) } ?? "unknown", privacy: .public)"
        )
    }
}

