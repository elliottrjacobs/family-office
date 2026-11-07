import Foundation

/// The setup dialog's steps, in order (plan R7).
public enum SetupStep: String, CaseIterable, Sendable, Identifiable {
    case welcome
    case office
    case engine
    case accounts
    case research
    case phone
    case done

    public var id: String { rawValue }

    /// The setup version that introduced the step. When `SetupFlow.currentVersion` is bumped,
    /// an install that finished an older version sees only the steps newer than it (R10).
    public var newSince: Int {
        switch self {
        case .welcome, .office, .engine, .accounts, .research, .phone, .done: return 1
        }
    }

    /// Steps the user may pass without finishing. The welcome step has nothing to finish,
    /// the office step is the one everything else needs, and done ends the dialog.
    public var canSkip: Bool {
        switch self {
        case .engine, .accounts, .research, .phone: return true
        case .welcome, .office, .done: return false
        }
    }

    /// Steps only a new office needs.
    var newOfficeOnly: Bool { self == .welcome || self == .office }
}

/// Whether the dialog is setting up a new office or finishing one that exists. It changes
/// the copy and where the dialog starts.
public enum SetupProfile: String, Sendable, Equatable {
    /// No office path is stored, or the stored folder has no `office.toml`.
    case new
    case existing

    public static func detect(officePath: String?, fileExists: (String) -> Bool) -> SetupProfile {
        guard let officePath, !officePath.isEmpty else { return .new }
        let toml = URL(fileURLWithPath: officePath).appendingPathComponent("office.toml").path
        return fileExists(toml) ? .existing : .new
    }
}

/// What happened at a step, for the done step's summary.
public enum SetupOutcome: Sendable, Equatable {
    /// Finished, with one line for the summary (`Office created`, `Default engine: Codex`).
    case completed(String)
    case skipped
}

/// Where keyboard focus is when Return is pressed.
public enum SetupFocus: Sendable, Equatable {
    /// A button, a list, or nothing in particular.
    case other
    /// A text or secure field: Return belongs to the field.
    case textField
    /// The embedded terminal: Return is the command's input.
    case terminal
}

/// The setup dialog's logic, kept free of UI so it can be tested: which steps to show, the
/// current step, skipping, the progress bar, and Return.
public struct SetupFlow: Sendable, Equatable {
    /// Bump when a release adds a step, and give that step a matching `newSince`.
    public static let currentVersion = 1

    public let profile: SetupProfile
    public let steps: [SetupStep]
    public private(set) var index = 0
    /// Choices patched per step as the user passes it.
    public private(set) var outcomes: [SetupStep: SetupOutcome] = [:]

    public init(steps: [SetupStep], profile: SetupProfile) {
        self.steps = steps.isEmpty ? [.done] : steps
        self.profile = profile
    }

    /// The steps for this launch.
    ///
    /// - A new profile always includes welcome and office: nothing works without an office.
    /// - An existing profile starts at engine; welcome and office are never shown again.
    /// - Opened from the Help menu (`manual`), or never finished (`stored` nil), every step
    ///   the profile allows is shown.
    /// - Otherwise only steps newer than `stored`, then done; none when `stored` is current.
    public static func steps(
        profile: SetupProfile, stored: Int?, current: Int = currentVersion, manual: Bool = false,
        newSince: (SetupStep) -> Int = { $0.newSince }
    ) -> [SetupStep] {
        let allowed = SetupStep.allCases.filter { profile == .new || !$0.newOfficeOnly }
        if manual { return allowed }
        guard let stored else { return allowed }
        let fresh = allowed.filter { step in
            step != .done && (newSince(step) > stored || (profile == .new && step.newOfficeOnly))
        }
        if fresh.isEmpty && stored >= current { return [] }
        return fresh + [.done]
    }

    /// Whether the dialog opens by itself at launch.
    public static func showsAtLaunch(
        profile: SetupProfile, stored: Int?, current: Int = currentVersion,
        newSince: (SetupStep) -> Int = { $0.newSince }
    ) -> Bool {
        !steps(profile: profile, stored: stored, current: current, newSince: newSince).isEmpty
    }

    public var current: SetupStep { steps[index] }
    public var isFirst: Bool { index == 0 }
    public var isLast: Bool { index == steps.count - 1 }
    public var canGoBack: Bool { index > 0 && current != .done }
    public var canSkip: Bool { current.canSkip }

    /// 0 on the first step, 1 on the last.
    public var progress: Double {
        steps.count <= 1 ? 1 : Double(index) / Double(steps.count - 1)
    }

    /// The current step finished; record its summary line, if it has one, and move on.
    public mutating func complete(_ summary: String? = nil) {
        if let summary { outcomes[current] = .completed(summary) }
        forward()
    }

    /// Passes the current step without finishing it. Refused where `canSkip` is false.
    @discardableResult
    public mutating func skip() -> Bool {
        guard canSkip else { return false }
        if case .completed? = outcomes[current] {
            // Done earlier and revisited with Back: keep what was finished.
        } else {
            outcomes[current] = .skipped
        }
        forward()
        return true
    }

    public mutating func back() {
        guard canGoBack else { return }
        index -= 1
    }

    private mutating func forward() {
        index = min(index + 1, steps.count - 1)
    }

    /// The summary on the done step, in step order: what is set up and what was skipped.
    public var summary: (completed: [String], skipped: [SetupStep]) {
        var completed: [String] = []
        var skipped: [SetupStep] = []
        for step in steps {
            switch outcomes[step] {
            case .completed(let line)?: completed.append(line)
            case .skipped?: skipped.append(step)
            case nil: break
            }
        }
        return (completed, skipped)
    }

    /// Return advances (the primary action) unless focus is in a text field or the terminal,
    /// where Return is input, and only when the primary action is available.
    public static func returnAdvances(focus: SetupFocus, primaryEnabled: Bool) -> Bool {
        primaryEnabled && focus == .other
    }
}
