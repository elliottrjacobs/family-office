import XCTest

@testable import FOKit

final class SetupTests: XCTestCase {
    func testProfileIsNewWithoutAStoredOfficeOrItsOfficeToml() {
        XCTAssertEqual(SetupProfile.detect(officePath: nil) { _ in true }, .new)
        XCTAssertEqual(SetupProfile.detect(officePath: "") { _ in true }, .new)
        XCTAssertEqual(SetupProfile.detect(officePath: "/tmp/empty") { _ in false }, .new)
        var asked: String?
        let profile = SetupProfile.detect(officePath: "/tmp/office") { path in
            asked = path
            return true
        }
        XCTAssertEqual(profile, .existing)
        XCTAssertEqual(asked, "/tmp/office/office.toml")
    }

    func testANewProfileShowsAllSevenSteps() {
        let steps = SetupFlow.steps(profile: .new, stored: nil)
        XCTAssertEqual(steps, [.welcome, .office, .engine, .accounts, .research, .phone, .done])
        XCTAssertTrue(SetupFlow.showsAtLaunch(profile: .new, stored: nil))
    }

    func testAnExistingProfileStartsAtTheEngineStep() {
        let steps = SetupFlow.steps(profile: .existing, stored: nil)
        XCTAssertEqual(steps, [.engine, .accounts, .research, .phone, .done])
        XCTAssertEqual(SetupFlow(steps: steps, profile: .existing).current, .engine)
        // The Help menu shows the same list, even after setup finished.
        XCTAssertEqual(SetupFlow.steps(profile: .existing, stored: 1, manual: true), steps)
    }

    func testAFinishedSetupDoesNotOpenAgain() {
        XCTAssertEqual(SetupFlow.steps(profile: .existing, stored: 1), [])
        XCTAssertFalse(SetupFlow.showsAtLaunch(profile: .existing, stored: 1))
        // Unless the office is gone: a new profile always needs the office step.
        XCTAssertEqual(SetupFlow.steps(profile: .new, stored: 1), [.welcome, .office, .done])
    }

    func testAVersionBumpShowsOnlyTheNewerSteps() {
        let newSince: (SetupStep) -> Int = { $0 == .research ? 2 : 1 }
        let steps = SetupFlow.steps(profile: .existing, stored: 1, current: 2, newSince: newSince)
        XCTAssertEqual(steps, [.research, .done])
        XCTAssertTrue(SetupFlow.showsAtLaunch(profile: .existing, stored: 1, current: 2, newSince: newSince))
        // Someone who finished version 2 already sees nothing.
        XCTAssertEqual(SetupFlow.steps(profile: .existing, stored: 2, current: 2, newSince: newSince), [])
        // Someone who never finished sees everything.
        XCTAssertEqual(
            SetupFlow.steps(profile: .existing, stored: nil, current: 2, newSince: newSince).count, 5)
    }

    func testEveryStepIsInTheCurrentVersion() {
        for step in SetupStep.allCases {
            XCTAssertLessThanOrEqual(step.newSince, SetupFlow.currentVersion)
        }
    }

    func testSkipRules() {
        XCTAssertEqual(SetupStep.allCases.filter(\.canSkip), [.engine, .accounts, .research, .phone])
        var flow = SetupFlow(steps: SetupFlow.steps(profile: .new, stored: nil), profile: .new)
        XCTAssertFalse(flow.skip(), "welcome cannot be skipped")
        flow.complete()
        XCTAssertEqual(flow.current, .office)
        XCTAssertFalse(flow.skip(), "office cannot be skipped")
        flow.complete("Office created")
        XCTAssertTrue(flow.skip())
        XCTAssertEqual(flow.current, .accounts)
        XCTAssertTrue(flow.skip())
        flow.complete("1 research key")
        XCTAssertTrue(flow.skip())
        XCTAssertEqual(flow.current, .done)
        XCTAssertFalse(flow.skip())
        XCTAssertFalse(flow.canGoBack)
        let summary = flow.summary
        XCTAssertEqual(summary.completed, ["Office created", "1 research key"])
        XCTAssertEqual(summary.skipped, [.engine, .accounts, .phone])
    }

    func testBackKeepsWhatWasFinished() {
        var flow = SetupFlow(steps: [.engine, .accounts, .done], profile: .existing)
        XCTAssertFalse(flow.canGoBack)
        flow.complete("Default engine: Claude Code")
        flow.back()
        XCTAssertEqual(flow.current, .engine)
        flow.skip()
        XCTAssertEqual(flow.outcomes[.engine], .completed("Default engine: Claude Code"))
    }

    func testProgressRunsFromZeroToOne() {
        var flow = SetupFlow(steps: [.engine, .accounts, .done], profile: .existing)
        XCTAssertEqual(flow.progress, 0)
        flow.skip()
        XCTAssertEqual(flow.progress, 0.5)
        flow.skip()
        XCTAssertEqual(flow.progress, 1)
        XCTAssertTrue(flow.isLast)
        XCTAssertEqual(SetupFlow(steps: [], profile: .existing).steps, [.done])
    }

    func testReturnAdvancesOutsideFieldsAndTheTerminal() {
        XCTAssertTrue(SetupFlow.returnAdvances(focus: .other, primaryEnabled: true))
        XCTAssertFalse(SetupFlow.returnAdvances(focus: .other, primaryEnabled: false))
        XCTAssertFalse(SetupFlow.returnAdvances(focus: .textField, primaryEnabled: true))
        XCTAssertFalse(SetupFlow.returnAdvances(focus: .terminal, primaryEnabled: true))
    }
}
