import AppKit
import Foundation
import Observation

/// The `fo` command for Terminal: a symlink at `/usr/local/bin/fo` to the app's bundled
/// `Contents/Resources/fo/bin/fo`, so the terminal runs exactly the version the app runs.
///
/// The app never escalates privileges. It makes the link itself when `/usr/local/bin` is
/// writable; otherwise it shows the exact command to paste into Terminal. It only replaces or
/// removes a link that points into a Family Office app bundle, never another `fo`.
@MainActor
@Observable
final class CommandLineTool {
    enum State: Equatable {
        /// This build has no bundled runtime (a development build), so there is nothing to link.
        case unavailable
        case notInstalled
        case installed
        /// Something else is at the link path: another `fo`, or a link to an older copy.
        case other(String)
    }

    static let linkPath = "/usr/local/bin/fo"
    static let bundledSuffix = "/Contents/Resources/fo/bin/fo"

    private(set) var state: State = .notInstalled
    /// A Terminal command to finish the job, when the app could not.
    private(set) var manualCommand: String?
    private(set) var message: String?

    @ObservationIgnored private let fileManager = FileManager.default

    init() {
        verify()
    }

    /// The launcher inside this app, when it exists.
    var target: String? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let path = resources.appendingPathComponent("fo/bin/fo").path
        return fileManager.isExecutableFile(atPath: path) ? path : nil
    }

    var stateText: String {
        switch state {
        case .unavailable: return "This build has no bundled runtime, so there is no fo to install."
        case .notInstalled: return "Not installed."
        case .installed: return "Installed at \(Self.linkPath)."
        case .other(let detail): return detail
        }
    }

    /// Reads what is at the link path now; called on launch and after every change.
    func verify() {
        guard let target else {
            state = .unavailable
            return
        }
        let link = Self.linkPath
        if let destination = try? fileManager.destinationOfSymbolicLink(atPath: link) {
            let resolved = Self.resolve(destination, relativeTo: link)
            if resolved == target || resolved == (target as NSString).resolvingSymlinksInPath {
                state = .installed
            } else if resolved.hasSuffix(Self.bundledSuffix) {
                state = .other("\(link) points to another copy of Family Office.")
            } else {
                state = .other("\(link) is a link to another fo.")
            }
        } else if fileManager.fileExists(atPath: link) {
            state = .other("\(link) is another program, not a link to this app.")
        } else {
            state = .notInstalled
        }
    }

    func install() {
        message = nil
        manualCommand = nil
        verify()
        guard let target, state != .installed else { return }
        let link = Self.linkPath
        let directory = (link as NSString).deletingLastPathComponent
        var replacing = false
        if case .other = state {
            guard isOurs(link) else {
                message = "Another fo is already installed there; the app leaves it alone."
                manualCommand = "sudo ln -sf \(Self.quote(target)) \(link)"
                return
            }
            replacing = true
        }
        guard fileManager.isWritableFile(atPath: directory) else {
            message = "\(directory) is not writable by you. Run this in Terminal:"
            let exists = fileManager.fileExists(atPath: directory)
            manualCommand =
                (exists ? "" : "sudo mkdir -p \(directory) && ")
                + "sudo ln -s\(replacing ? "f" : "") \(Self.quote(target)) \(link)"
            return
        }
        do {
            if replacing {
                try fileManager.removeItem(atPath: link)
            }
            try fileManager.createSymbolicLink(atPath: link, withDestinationPath: target)
            message = "Installed. Open a new Terminal window and run fo --version."
        } catch {
            message = "The link could not be created. Run this in Terminal:"
            manualCommand = "sudo ln -sf \(Self.quote(target)) \(link)"
        }
        verify()
    }

    func remove() {
        message = nil
        manualCommand = nil
        let link = Self.linkPath
        guard isOurs(link) else {
            message = "\(link) is not a Family Office link; the app leaves it alone."
            return
        }
        do {
            try fileManager.removeItem(atPath: link)
            message = "Removed."
        } catch {
            message = "The link could not be removed. Run this in Terminal:"
            manualCommand = "sudo rm \(link)"
        }
        verify()
    }

    func copyManualCommand() {
        guard let manualCommand else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(manualCommand, forType: .string)
    }

    func openTerminal() {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Terminal")
        else { return }
        NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
    }

    /// True for a symlink into any Family Office app bundle.
    private func isOurs(_ link: String) -> Bool {
        guard let destination = try? fileManager.destinationOfSymbolicLink(atPath: link) else {
            return false
        }
        return Self.resolve(destination, relativeTo: link).hasSuffix(Self.bundledSuffix)
    }

    private static func resolve(_ destination: String, relativeTo link: String) -> String {
        guard !destination.hasPrefix("/") else { return destination }
        let base = (link as NSString).deletingLastPathComponent
        return ((base as NSString).appendingPathComponent(destination) as NSString).standardizingPath
    }

    /// Single-quotes a path for the shell.
    static func quote(_ path: String) -> String {
        "'" + path.replacingOccurrences(of: "'", with: #"'\''"#) + "'"
    }
}
