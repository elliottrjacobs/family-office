import FOKit
import Foundation

/// The setup version this install finished, kept in `UserDefaults` as `setupVersion` (R10).
///
/// The dialog opens by itself while no version is stored, and again after a release raises
/// `SetupFlow.currentVersion`, showing only the steps whose `newSince` is newer than the
/// stored version. Finishing the dialog stores the current version.
@MainActor
enum SetupVersion {
    static let key = "setupVersion"

    private static var defaults: UserDefaults { .standard }

    /// The version this build ships. Debug builds accept `-debugSetupVersion N` to pretend
    /// a release raised it.
    static var current: Int {
        #if DEBUG
        if defaults.object(forKey: "debugSetupVersion") != nil {
            return defaults.integer(forKey: "debugSetupVersion")
        }
        #endif
        return SetupFlow.currentVersion
    }

    /// The version stored when setup last finished, or nil. Debug builds accept
    /// `-debugIgnoreSetupVersion YES` to act as a first launch without clearing defaults.
    static var stored: Int? {
        #if DEBUG
        if defaults.bool(forKey: "debugIgnoreSetupVersion") { return nil }
        #endif
        return defaults.object(forKey: key) == nil ? nil : defaults.integer(forKey: key)
    }

    /// The version a step arrived in. Debug builds accept `-debugNewSteps research,phone`,
    /// which marks those steps as new in `current`, to see a version bump re-show them.
    static func newSince(_ step: SetupStep) -> Int {
        #if DEBUG
        if let names = defaults.string(forKey: "debugNewSteps"),
            names.split(separator: ",").map(String.init).contains(step.rawValue)
        {
            return current
        }
        #endif
        return step.newSince
    }

    static func markFinished() {
        defaults.set(current, forKey: key)
    }
}
