import XCTest

@testable import FOKit

final class WebActionTests: XCTestCase {
    func testParsesTheActionsThePageOffers() {
        XCTAssertEqual(WebAction("setup"), .setup)
        XCTAssertEqual(WebAction("settings:connectors"), .settings(tab: "connectors"))
        XCTAssertEqual(WebAction("settings:engines"), .settings(tab: "engines"))
        XCTAssertEqual(WebAction("settings:devices"), .settings(tab: "devices"))
    }

    func testIgnoresEverythingElse() {
        let refused = [
            "", "sync", "settings", "settings:", "settings:terminal", "settings:connectors:x",
            "open:/etc", "SETUP", "settings:../general",
        ]
        for text in refused {
            XCTAssertNil(WebAction(text), "\(text) should be ignored")
        }
        XCTAssertNil(WebAction(nil))
    }
}
