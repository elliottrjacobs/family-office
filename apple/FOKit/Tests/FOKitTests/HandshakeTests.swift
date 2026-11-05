import XCTest

@testable import FOKit

final class HandshakeTests: XCTestCase {
    private let token = "constant-test-token"

    func testParsesValidLine() throws {
        let line =
            #"{"port": 4790, "token": "constant-test-token", "office": "/tmp/example-office", "#
            + #""state": "ready", "version": "2.0.0"}"# + "\n"
        let handshake = try Handshake.parse(line: line)
        XCTAssertEqual(handshake.port, 4790)
        XCTAssertEqual(handshake.token, token)
        XCTAssertEqual(handshake.office, "/tmp/example-office")
        XCTAssertEqual(handshake.state, "ready")
        XCTAssertEqual(handshake.version, "2.0.0")
        XCTAssertEqual(handshake.baseURL.absoluteString, "http://127.0.0.1:4790/")
        XCTAssertEqual(
            handshake.landingURL.absoluteString, "http://127.0.0.1:4790/?t=constant-test-token")
    }

    func testNullOfficeIsAllowed() throws {
        let handshake = try Handshake.parse(
            line: #"{"port": 4790, "token": "x", "office": null, "state": "no_office", "version": "2.0.0"}"#)
        XCTAssertNil(handshake.office)
        XCTAssertEqual(handshake.state, "no_office")
    }

    func testRejectsMissingPort() {
        XCTAssertThrowsError(
            try Handshake.parse(line: #"{"token": "x", "office": null, "state": "ready", "version": "2.0.0"}"#)
        ) { error in
            XCTAssertEqual(error as? HandshakeError, .missingField("port"))
        }
    }

    func testRejectsMissingToken() {
        XCTAssertThrowsError(
            try Handshake.parse(line: #"{"port": 4790, "office": null, "state": "ready", "version": "2.0.0"}"#)
        ) { error in
            XCTAssertEqual(error as? HandshakeError, .missingField("token"))
        }
    }

    func testRejectsTrailingGarbage() {
        XCTAssertThrowsError(
            try Handshake.parse(
                line: #"{"port": 4790, "token": "x", "state": "ready", "version": "2.0.0"} trailing"#)
        ) { error in
            XCTAssertEqual(error as? HandshakeError, .notJSON)
        }
    }

    func testRejectsPlainTextAndBadValues() {
        XCTAssertThrowsError(try Handshake.parse(line: "Family Office companion app")) { error in
            XCTAssertEqual(error as? HandshakeError, .notJSON)
        }
        XCTAssertThrowsError(try Handshake.parse(line: #"{"port": 0, "token": "x"}"#)) { error in
            XCTAssertEqual(error as? HandshakeError, .invalid("port"))
        }
        XCTAssertThrowsError(try Handshake.parse(line: #"{"port": 4790, "token": ""}"#)) { error in
            XCTAssertEqual(error as? HandshakeError, .invalid("token"))
        }
    }

    func testDescriptionOmitsToken() throws {
        let handshake = try Handshake.parse(line: #"{"port": 4790, "token": "constant-test-token"}"#)
        XCTAssertFalse(handshake.description.contains(token))
        XCTAssertFalse(String(reflecting: handshake).contains(token))
        XCTAssertFalse("\(handshake)".contains(token))
    }

    func testOpenLineFallback() {
        let handshake = Handshake.parseOpenLine("  Open: http://127.0.0.1:59437/?t=constant-test-token")
        XCTAssertEqual(handshake?.port, 59437)
        XCTAssertEqual(handshake?.token, token)
        XCTAssertNil(Handshake.parseOpenLine("  Office: /tmp/example-office"))
        XCTAssertNil(Handshake.parseOpenLine("  Open: http://example.com:80/?t=x"))
        XCTAssertNil(Handshake.parseOpenLine("  Open: http://127.0.0.1:4790/"))
    }
}
