import CoreGraphics
import CoreImage
import Foundation

/// What the pairing QR code carries: `{"v":1,"url":"https://<tailnet_name>","code":"<code>"}`.
///
/// The iOS app scans it, posts `code` to `<url>/api/devices/pair` over the tailnet, and keeps
/// the device token it gets back. The code is single use and expires in five minutes, so the
/// payload is worthless once used or expired; it is still never logged.
public struct PairingPayload: Codable, Sendable, Equatable {
    public static let version = 1

    public let v: Int
    public let url: String
    public let code: String

    public init(v: Int = PairingPayload.version, url: String, code: String) {
        self.v = v
        self.url = url
        self.code = code
    }

    /// The payload for a tailnet name such as `example-mac.tail0000.ts.net`. A scheme, path or
    /// trailing dot in the name is dropped; the URL is always `https://<host>`.
    public init(tailnetName: String, code: String) {
        self.init(url: "https://" + Self.host(tailnetName), code: code)
    }

    static func host(_ name: String) -> String {
        var host = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if let range = host.range(of: "://") {
            host = String(host[range.upperBound...])
        }
        if let slash = host.firstIndex(of: "/") {
            host = String(host[..<slash])
        }
        while host.hasSuffix(".") {
            host.removeLast()
        }
        return host.lowercased()
    }

    /// Compact JSON with the keys in the documented order: `v`, `url`, `code`.
    public func encoded() -> String {
        "{\"v\":\(v),\"url\":\(Self.literal(url)),\"code\":\(Self.literal(code))}"
    }

    private static func literal(_ text: String) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        guard let data = try? encoder.encode(text) else { return "\"\"" }
        return String(decoding: data, as: UTF8.self)
    }

    public enum DecodeError: Error, Equatable, Sendable {
        case notJSON
        case unsupportedVersion(Int)
        case invalid(String)
    }

    /// Parses a scanned payload; the phone uses this. Refuses other versions and non-HTTPS URLs.
    public static func decode(_ text: String) throws -> PairingPayload {
        let payload: PairingPayload
        do {
            payload = try JSONDecoder().decode(PairingPayload.self, from: Data(text.utf8))
        } catch {
            throw DecodeError.notJSON
        }
        guard payload.v == version else { throw DecodeError.unsupportedVersion(payload.v) }
        guard let components = URLComponents(string: payload.url), components.scheme == "https",
            let host = components.host, !host.isEmpty
        else { throw DecodeError.invalid("url") }
        guard !payload.code.isEmpty else { throw DecodeError.invalid("code") }
        return payload
    }
}

extension PairingPayload: CustomStringConvertible, CustomDebugStringConvertible {
    public var description: String { "PairingPayload(v: \(v), url: \(url))" }
    public var debugDescription: String { description }
}

public enum Pairing {
    /// Whole seconds left before `expiry`, never negative.
    public static func secondsRemaining(until expiry: Date, now: Date = Date()) -> Int {
        max(0, Int(expiry.timeIntervalSince(now).rounded(.down)))
    }

    /// `4:05` for 245 seconds.
    public static func countdown(_ seconds: Int) -> String {
        let seconds = max(0, seconds)
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    /// The code grouped for reading aloud: `ABCD-2345`. The server ignores hyphens.
    public static func grouped(_ code: String) -> String {
        guard code.count == 8 else { return code }
        return "\(code.prefix(4))-\(code.suffix(4))"
    }

    /// Plain words for the server's refusals on the device routes.
    public static func explain(_ error: Error) -> String {
        guard let error = error as? APIError else { return "The request failed." }
        switch error {
        case .http(_, let reason?):
            switch reason {
            case "loopback_only": return "Ask for a pairing code on this Mac."
            case "launch_cookie_required": return "Manage devices from the Mac app."
            case "device_not_found": return "That device is no longer paired."
            case "forbidden_origin": return "The server refused the request's origin."
            case "office_not_found": return "Choose or set up an office first."
            default: return "The server refused the request (\(reason))."
            }
        case .http(let status, nil):
            return "The server answered with HTTP \(status)."
        case .transport(let detail):
            return "The server is not reachable (\(detail))."
        case .decoding:
            return "The server's answer was not understood."
        }
    }
}

/// QR codes rendered with Core Image's `CIQRCodeGenerator`.
public enum QRCode {
    /// A black-on-white QR code for `text`, `scale` pixels per module, with a four-module
    /// quiet zone so scanners and `CIDetector` find it reliably.
    public static func image(for text: String, scale: CGFloat = 10, correction: String = "M")
        -> CGImage?
    {
        guard let filter = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        filter.setValue(Data(text.utf8), forKey: "inputMessage")
        filter.setValue(correction, forKey: "inputCorrectionLevel")
        guard let code = filter.outputImage else { return nil }
        let quiet: CGFloat = 4
        let padded = code.transformed(by: CGAffineTransform(translationX: quiet, y: quiet))
        let side = CGRect(
            x: 0, y: 0, width: code.extent.width + 2 * quiet, height: code.extent.height + 2 * quiet)
        let white = CIImage(color: CIColor(red: 1, green: 1, blue: 1)).cropped(to: side)
        let composed = padded.composited(over: white).samplingNearest()
            .transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let context = CIContext(options: [.useSoftwareRenderer: false])
        return context.createCGImage(composed, from: composed.extent)
    }
}
