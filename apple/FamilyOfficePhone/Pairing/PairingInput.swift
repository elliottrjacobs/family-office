import FOKit
import Foundation

/// Turns what the scanner read, or what was typed, into a pairing payload, with a sentence
/// to show when it is not one. The scanned text is never logged: it holds a live code.
enum PairingInput {
    struct Failure: Error, Equatable {
        let message: String
    }

    static func payload(fromScanned text: String) -> Result<PairingPayload, Failure> {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            return .success(try PairingPayload.decode(trimmed))
        } catch let error as PairingPayload.DecodeError {
            return .failure(Failure(message: message(for: error)))
        } catch {
            return .failure(Failure(message: "That QR code could not be read."))
        }
    }

    static func payload(url: String, code: String) -> Result<PairingPayload, Failure> {
        do {
            return .success(try PairingPayload.manual(url: url, code: code))
        } catch PairingPayload.DecodeError.invalid("code") {
            return .failure(Failure(message: "Type the code the Mac shows, such as ABCD-2345."))
        } catch {
            return .failure(
                Failure(
                    message: "Type the Mac's tailnet address, such as example-mac.tail0000.ts.net."))
        }
    }

    static func message(for error: PairingPayload.DecodeError) -> String {
        switch error {
        case .notJSON:
            return "That QR code is not a Family Office pairing code. On the Mac, open Settings > Devices and click Pair a Phone."
        case .unsupportedVersion:
            return "That pairing code comes from a newer Family Office. Update this app, then scan again."
        case .invalid(let field) where field == "code":
            return "That pairing code has no code in it. Show a new one on the Mac."
        case .invalid:
            return "That pairing code has no HTTPS tailnet address. Set the tailnet name on the Mac in Settings > Devices."
        }
    }
}
