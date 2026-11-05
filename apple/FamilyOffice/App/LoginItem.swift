import Foundation
import Observation
import ServiceManagement

/// Launch at login through `SMAppService.mainApp`. The status always mirrors what macOS reports,
/// so a change made in System Settings shows up the next time the pane refreshes.
@MainActor
@Observable
final class LoginItem {
    private(set) var status: SMAppService.Status = .notRegistered
    private(set) var failure: String?

    init() {
        refresh()
    }

    /// The toggle is on when registered, including while macOS waits for the user's approval.
    var isOn: Bool { status == .enabled || status == .requiresApproval }

    var needsApproval: Bool { status == .requiresApproval }

    var statusText: String {
        if let failure { return failure }
        switch status {
        case .enabled: return "Family Office opens when you log in."
        case .requiresApproval:
            return "Allow Family Office in System Settings > General > Login Items to finish."
        case .notRegistered: return "Family Office opens only when you open it."
        case .notFound:
            return "macOS cannot register this copy. Move the app to Applications and try again."
        @unknown default: return "macOS reported an unknown login item state."
        }
    }

    func refresh() {
        status = SMAppService.mainApp.status
    }

    func setEnabled(_ on: Bool) {
        failure = nil
        do {
            if on {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            // The code is enough to look up; the description may name paths.
            let code = (error as NSError).code
            failure =
                on
                ? "macOS did not turn on launch at login (error \(code))."
                : "macOS did not turn off launch at login (error \(code))."
        }
        refresh()
    }

    /// Opens System Settings > General > Login Items.
    func openSystemSettings() {
        SMAppService.openSystemSettingsLoginItems()
    }
}
