import Foundation
import Observation
import Sparkle
import os

/// In-app updates through Sparkle: the app menu's Check for Updates… item and the automatic
/// check preference in Settings > General.
///
/// The feed (`SUFeedURL`) is the `appcast.xml` attached to the latest GitHub Release, and every
/// download must carry an EdDSA signature that verifies against `SUPublicEDKey` in Info.plist.
/// Until the real public key replaces the placeholder (see RELEASING.md) the updater is not
/// started, so development builds never show Sparkle's "failed to start" alert.
@MainActor
@Observable
final class Updater {
    /// The value project.yml ships until the release keypair exists.
    static let placeholderKey = "SPARKLE_PUBLIC_ED_KEY_PLACEHOLDER"

    /// False while Info.plist carries the placeholder key (or no key or feed at all).
    let configured: Bool
    /// Mirrors `SPUUpdater.canCheckForUpdates`: false while a check is already in progress.
    private(set) var canCheckForUpdates = false
    /// Mirrors `SPUUpdater.automaticallyChecksForUpdates`, which Sparkle stores in user defaults.
    private(set) var automaticallyChecks = true

    @ObservationIgnored private let controller: SPUStandardUpdaterController
    @ObservationIgnored private var observation: NSKeyValueObservation?
    @ObservationIgnored private let log = Logger(subsystem: "com.familyoffice.app", category: "updates")

    init(bundle: Bundle = .main) {
        let key = bundle.object(forInfoDictionaryKey: "SUPublicEDKey") as? String ?? ""
        let feed = bundle.object(forInfoDictionaryKey: "SUFeedURL") as? String ?? ""
        configured = !key.isEmpty && key != Self.placeholderKey && !feed.isEmpty
        controller = SPUStandardUpdaterController(
            startingUpdater: configured, updaterDelegate: nil, userDriverDelegate: nil)
        guard configured else {
            log.info("updates: not configured (placeholder public key); updater not started")
            return
        }
        let updater = controller.updater
        automaticallyChecks = updater.automaticallyChecksForUpdates
        canCheckForUpdates = updater.canCheckForUpdates
        observation = updater.observe(\.canCheckForUpdates, options: [.new]) { [weak self] _, change in
            let value = change.newValue ?? false
            Task { @MainActor in self?.canCheckForUpdates = value }
        }
    }

    /// Shows Sparkle's standard update UI (or "You're up to date").
    func checkForUpdates() {
        guard configured else { return }
        controller.checkForUpdates(nil)
    }

    func setAutomaticallyChecks(_ on: Bool) {
        guard configured else { return }
        controller.updater.automaticallyChecksForUpdates = on
        automaticallyChecks = on
        log.info("updates: automatic checks \(on ? "on" : "off", privacy: .public)")
    }

    var statusText: String {
        guard configured else {
            return "Updates are not set up in this build (no release signing key)."
        }
        if let last = controller.updater.lastUpdateCheckDate {
            return "Last checked \(last.formatted(date: .abbreviated, time: .shortened))."
        }
        return "Not checked yet."
    }
}

