import Foundation
import XCTest

@testable import FOKit

final class ConnectorsTests: XCTestCase {
    private func connector(_ id: String) -> Connector {
        ConnectorCatalog.connector(id)!
    }

    private func config(_ json: String) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(json.utf8))
    }

    func testCatalogListsEveryProviderOnce() {
        XCTAssertEqual(
            ConnectorCatalog.all.map(\.id),
            ["schwab", "simplefin", "alphavantage", "fred", "exa", "firecrawl", "gemini", "edgar"])
        XCTAssertEqual(ConnectCommand.keyProviders, ["alphavantage", "fred", "exa", "firecrawl", "gemini"])
        XCTAssertEqual(Set(ConnectorCatalog.all.filter { $0.kind == .account }.map(\.id)), Set(TerminalCommand.authProviders))
    }

    // MARK: - Commands

    func testSaveNeverPutsTheKeyInTheArguments() throws {
        let key = "synthetic-key-0123456789"
        XCTAssertEqual(ConnectCommand.save("exa"), ["connect", "exa"])
        let stdin = try XCTUnwrap(ConnectCommand.stdin(forKey: "  \(key)\n"))
        XCTAssertEqual(String(decoding: stdin, as: UTF8.self), key + "\n")
        XCTAssertFalse(ConnectCommand.save("exa")!.contains(key))
    }

    func testRejectsKeysFoConnectWouldRefuse() {
        XCTAssertNil(ConnectCommand.stdin(forKey: ""))
        XCTAssertNil(ConnectCommand.stdin(forKey: "   "))
        XCTAssertNil(ConnectCommand.stdin(forKey: "two words"))
        XCTAssertNil(ConnectCommand.stdin(forKey: "tab\there"))
        XCTAssertNil(ConnectCommand.stdin(forKey: String(repeating: "k", count: 513)))
        XCTAssertNotNil(ConnectCommand.stdin(forKey: String(repeating: "k", count: 512)))
    }

    func testOnlyKeyProvidersSaveAndAccountsCannotBeRemovedHere() {
        XCTAssertNil(ConnectCommand.save("schwab"))
        XCTAssertNil(ConnectCommand.save("edgar"))
        XCTAssertNil(ConnectCommand.save("unknown"))
        XCTAssertEqual(ConnectCommand.remove("gemini"), ["connect", "--remove", "gemini"])
        XCTAssertEqual(ConnectCommand.remove("edgar"), ["connect", "--remove", "edgar"])
        XCTAssertNil(ConnectCommand.remove("schwab"))
        XCTAssertNil(ConnectCommand.remove("unknown"))
    }

    func testEdgarUserAgent() {
        XCTAssertEqual(
            ConnectCommand.edgar(name: "  Pat   Example ", email: " pat@example.com "),
            ["connect", "edgar", "--user-agent", "Pat Example pat@example.com"])
    }

    // MARK: - States

    func testNothingKnownWithoutTheServer() {
        let states = ConnectorStates()
        XCTAssertEqual(states.state(connector("schwab")), .notConnected)
        XCTAssertEqual(states.state(connector("exa")), .notReported)
        XCTAssertEqual(states.state(connector("edgar")), .notReported)
    }

    func testAccountsFromOnboardingThenMaskedSecrets() throws {
        var states = ConnectorStates(
            onboarding: [Onboarding.Provider(provider: "schwab", connected: true, accounts: 2)],
            config: try config(#"{"settings": {}, "secrets": {"simplefin": {"access_url": "***"}}}"#))
        XCTAssertEqual(states.state(connector("schwab")), .connected)
        XCTAssertEqual(states.state(connector("simplefin")), .connected)
        states.onboarding = [Onboarding.Provider(provider: "simplefin", connected: false, accounts: 0)]
        XCTAssertEqual(states.state(connector("simplefin")), .notConnected)
        XCTAssertEqual(states.state(connector("schwab")), .notConnected)
    }

    func testKeyProvidersFromMaskedSecretsOrTheLastSave() throws {
        var states = ConnectorStates(
            config: try config(#"{"settings": {}, "secrets": {"alphavantage": {"api_key": "***"}}}"#))
        XCTAssertEqual(states.state(connector("alphavantage")), .connected)
        // The route reports every stored key, so one it does not list is not connected.
        XCTAssertEqual(states.state(connector("fred")), .notConnected)

        states.outcomes["fred"] = ConnectOutcome(connected: true, succeeded: true, message: "Saved.")
        XCTAssertEqual(states.state(connector("fred")), .connected)

        // A refused Save changes nothing.
        states.outcomes["exa"] = ConnectOutcome(
            connected: false, succeeded: false, message: "The provider rejected the API key.")
        XCTAssertEqual(states.state(connector("exa")), .notConnected)

        states.outcomes["alphavantage"] = ConnectOutcome(connected: false, succeeded: true, message: "Removed.")
        XCTAssertEqual(states.state(connector("alphavantage")), .notConnected)
    }

    func testEdgarFromSettings() throws {
        var states = ConnectorStates(
            config: try config(
                #"{"settings": {"providers": {"edgar": {"user_agent": "Pat Example pat@example.com"}}}, "secrets": {}}"#
            ))
        XCTAssertEqual(states.state(connector("edgar")), .connected)
        XCTAssertEqual(states.edgarUserAgent, "Pat Example pat@example.com")
        states.config = try config(#"{"settings": {}, "secrets": {}}"#)
        XCTAssertEqual(states.state(connector("edgar")), .notConnected)
        XCTAssertNil(states.edgarUserAgent)
    }

    func testOutcomeHoldsNoKey() {
        let outcome = ConnectOutcome(connected: true, succeeded: true, message: "Saved.")
        XCTAssertFalse(String(describing: outcome).contains("synthetic-key"))
    }
}
