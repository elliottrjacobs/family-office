import FOKit
import XCTest

@testable import FamilyOfficePhone

/// What the scanner hands over is the QR code's text; these turn it into a payload or a
/// sentence. Synthetic values only.
final class PairingInputTests: XCTestCase {
    func testScannedPayloadParses() throws {
        let scanned = " {\"v\":1,\"url\":\"https://example-mac.tail0000.ts.net\",\"code\":\"ABCD2345\"}\n"
        let payload = try PairingInput.payload(fromScanned: scanned).get()
        XCTAssertEqual(payload, PairingPayload(url: "https://example-mac.tail0000.ts.net", code: "ABCD2345"))
        XCTAssertFalse(String(describing: payload).contains("ABCD2345"))
    }

    func testScannedTextThatIsNotAPairingCodeIsExplained() {
        let cases: [(String, String)] = [
            ("https://example.com", "not a Family Office pairing code"),
            ("{\"v\":2,\"url\":\"https://example-mac.tail0000.ts.net\",\"code\":\"ABCD2345\"}", "newer Family Office"),
            ("{\"v\":1,\"url\":\"http://example-mac.tail0000.ts.net\",\"code\":\"ABCD2345\"}", "HTTPS tailnet address"),
            ("{\"v\":1,\"url\":\"https://example-mac.tail0000.ts.net\",\"code\":\"\"}", "no code"),
        ]
        for (text, expected) in cases {
            guard case .failure(let failure) = PairingInput.payload(fromScanned: text) else {
                XCTFail("\(text) should not parse")
                continue
            }
            XCTAssertTrue(failure.message.contains(expected), failure.message)
        }
    }
}
