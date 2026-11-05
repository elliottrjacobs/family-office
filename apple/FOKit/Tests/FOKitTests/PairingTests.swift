import CoreImage
import Foundation
import XCTest

@testable import FOKit

/// The QR payload, its encoding, and a round trip through `CIQRCodeGenerator` and `CIDetector`.
final class PairingTests: XCTestCase {
    private let tailnet = "example-mac.tail0000.ts.net"
    private let code = "ABCD2345"

    func testEncodesTheDocumentedPayload() {
        let payload = PairingPayload(tailnetName: tailnet, code: code)
        XCTAssertEqual(
            payload.encoded(),
            #"{"v":1,"url":"https://example-mac.tail0000.ts.net","code":"ABCD2345"}"#)
    }

    func testNormalizesTheTailnetName() {
        for input in [
            "example-mac.tail0000.ts.net.", "https://example-mac.tail0000.ts.net/",
            " Example-Mac.tail0000.ts.net ",
        ] {
            XCTAssertEqual(
                PairingPayload(tailnetName: input, code: code).url,
                "https://example-mac.tail0000.ts.net", input)
        }
    }

    func testEscapesValues() throws {
        let payload = PairingPayload(url: "https://example-mac.tail0000.ts.net", code: #"A"B\C"#)
        let decoded = try JSONDecoder().decode(PairingPayload.self, from: Data(payload.encoded().utf8))
        XCTAssertEqual(decoded, payload)
    }

    func testDecodeChecksVersionAndScheme() throws {
        let good = PairingPayload(tailnetName: tailnet, code: code)
        XCTAssertEqual(try PairingPayload.decode(good.encoded()), good)
        XCTAssertThrowsError(try PairingPayload.decode(#"{"v":2,"url":"https://x.ts.net","code":"A"}"#)) {
            XCTAssertEqual($0 as? PairingPayload.DecodeError, .unsupportedVersion(2))
        }
        XCTAssertThrowsError(try PairingPayload.decode(#"{"v":1,"url":"http://x.ts.net","code":"A"}"#)) {
            XCTAssertEqual($0 as? PairingPayload.DecodeError, .invalid("url"))
        }
        XCTAssertThrowsError(try PairingPayload.decode("ABCD2345")) {
            XCTAssertEqual($0 as? PairingPayload.DecodeError, .notJSON)
        }
    }

    func testDescriptionKeepsTheCodeOut() {
        let payload = PairingPayload(tailnetName: tailnet, code: code)
        XCTAssertFalse(String(describing: payload).contains(code))
        XCTAssertFalse(String(reflecting: payload).contains(code))
    }

    func testCountdownAndGrouping() {
        let now = Date(timeIntervalSince1970: 1_000)
        XCTAssertEqual(Pairing.secondsRemaining(until: now.addingTimeInterval(245.7), now: now), 245)
        XCTAssertEqual(Pairing.secondsRemaining(until: now.addingTimeInterval(-5), now: now), 0)
        XCTAssertEqual(Pairing.countdown(245), "4:05")
        XCTAssertEqual(Pairing.countdown(0), "0:00")
        XCTAssertEqual(Pairing.grouped("ABCD2345"), "ABCD-2345")
        XCTAssertEqual(Pairing.grouped("ABC"), "ABC")
    }

    func testQRCodeDecodesToThePayload() throws {
        let payload = PairingPayload(tailnetName: tailnet, code: code)
        let image = try XCTUnwrap(QRCode.image(for: payload.encoded()))
        XCTAssertGreaterThan(image.width, 200)
        let detector = try XCTUnwrap(
            CIDetector(
                ofType: CIDetectorTypeQRCode, context: nil,
                options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]))
        let features = detector.features(in: CIImage(cgImage: image))
        let message = try XCTUnwrap((features.first as? CIQRCodeFeature)?.messageString)
        XCTAssertEqual(message, payload.encoded())
        XCTAssertEqual(try PairingPayload.decode(message), payload)
    }
}
