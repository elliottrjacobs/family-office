import Foundation
import IOKit.pwr_mgt
import Observation
import os

/// Keeps the Mac from idle-sleeping while a phone is paired, so the phone can reach the office.
///
/// One `PreventUserIdleSystemSleep` assertion, held only while the keep-awake setting is on and
/// at least one device is paired, released as soon as either stops being true and when the app
/// quits. The display may still sleep; closing the lid or choosing Sleep still sleeps.
@MainActor
@Observable
final class Power {
    /// `UserDefaults` key for the keep-awake setting.
    static let keepAwakeKey = "keepAwakeWhilePaired"
    static let reason = "Family Office keeps this Mac awake so a paired phone can reach it."

    private(set) var keepAwake: Bool
    /// Paired devices as last reported by the server.
    private(set) var deviceCount = 0
    /// True while the assertion is held.
    private(set) var assertionHeld = false
    /// Set when macOS refused the assertion.
    private(set) var failure: String?

    @ObservationIgnored private var assertion: IOPMAssertionID = 0
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let log = Logger(subsystem: "com.familyoffice.app", category: "power")

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        keepAwake = defaults.bool(forKey: Self.keepAwakeKey)
    }

    /// The toggle is available only once a phone is paired.
    var available: Bool { deviceCount > 0 }

    var stateText: String {
        if let failure { return failure }
        if assertionHeld { return "This Mac stays awake while a phone is paired." }
        if !available { return "Pair a phone in Devices first." }
        return keepAwake ? "Waiting for a paired phone." : "The Mac sleeps as usual."
    }

    func setKeepAwake(_ on: Bool) {
        keepAwake = on
        defaults.set(on, forKey: Self.keepAwakeKey)
        apply()
    }

    func update(deviceCount: Int) {
        if deviceCount != self.deviceCount {
            self.deviceCount = deviceCount
        }
        apply()
    }

    /// Releases the assertion; called when the app quits.
    func release() {
        guard assertionHeld else { return }
        IOPMAssertionRelease(assertion)
        assertion = 0
        assertionHeld = false
        log.info("released the keep-awake assertion")
    }

    private func apply() {
        let wanted = keepAwake && deviceCount > 0
        if wanted, !assertionHeld {
            var id: IOPMAssertionID = 0
            let result = IOPMAssertionCreateWithName(
                kIOPMAssertionTypePreventUserIdleSystemSleep as CFString,
                IOPMAssertionLevel(kIOPMAssertionLevelOn), Self.reason as CFString, &id)
            if result == kIOReturnSuccess {
                assertion = id
                assertionHeld = true
                failure = nil
                log.info("holding the keep-awake assertion")
            } else {
                failure = "macOS refused to keep the Mac awake (IOReturn \(result))."
                log.error("keep-awake assertion refused: \(result, privacy: .public)")
            }
        } else if !wanted {
            failure = nil
            release()
        }
    }
}
