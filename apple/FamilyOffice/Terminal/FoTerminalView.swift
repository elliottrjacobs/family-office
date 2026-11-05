import AppKit
import FOKit
import Observation
import SwiftTerm
import SwiftUI
import os

let terminalLog = Logger(subsystem: "com.familyoffice.app", category: "terminal")

/// One run of one allowed `fo` command in a pseudo-terminal.
///
/// - Only `TerminalCommand` values run (`setup`, `auth schwab|simplefin`, `sync`, `doctor`);
///   raw words outside that set are refused before any process exists.
/// - The executable is the same `fo` the server runs, with `--office PATH` first and the
///   server's scrubbed environment plus `TERM`. It is started directly with `forkpty` and
///   `execve`: no shell is ever involved.
/// - Output lives only in the terminal's in-memory buffer and is never logged or written.
@MainActor
@Observable
final class FoTerminalSession: Identifiable {
    enum Phase: Equatable {
        case ready
        case running
        case exited(Int32?)
        /// Not started: the command is not allowed, or `fo` or the office is missing.
        case refused(String)
    }

    let id = UUID()
    let command: TerminalCommand?
    let office: String?
    private(set) var phase: Phase
    /// Called once when the process ends, with its exit status.
    @ObservationIgnored var onExit: ((Int32?) -> Void)?

    init(command: TerminalCommand, office: String?) {
        self.command = command
        self.office = office
        phase = .ready
    }

    /// For words that may come from outside the app (the Debug launch argument): anything
    /// that is not an allowed command is refused here.
    init(words: [String], office: String?) {
        command = TerminalCommand(words)
        self.office = office
        phase = command == nil ? .refused(Self.notAllowed) : .ready
        if command == nil {
            terminalLog.info("terminal: refused a command outside the allowed set")
        }
    }

    static let notAllowed =
        "The terminal runs only fo setup, fo auth schwab, fo auth simplefin, fo sync and fo doctor."

    var title: String { command?.title ?? "Terminal" }
    var explanation: String { command?.explanation ?? "" }
    var isRunning: Bool { phase == .running }

    /// What to launch, or nil after recording why not.
    func prepare() -> (executable: URL, arguments: [String], environment: [String])? {
        guard phase == .ready else { return nil }
        guard let command else {
            phase = .refused(Self.notAllowed)
            return nil
        }
        guard let office, let arguments = command.arguments(office: office) else {
            phase = .refused("Choose an office folder in General first.")
            return nil
        }
        guard let executable = ServerProcess.resolveExecutable() else {
            phase = .refused(FoCommandError.missing.message)
            return nil
        }
        var environment = ServerProcess.environment(binDirectory: executable.deletingLastPathComponent())
        environment["TERM"] = "xterm-256color"
        phase = .running
        terminalLog.info("terminal: started \(command.words.first ?? "", privacy: .public)")
        return (
            executable, arguments,
            environment.map { "\($0.key)=\($0.value)" }.sorted()
        )
    }

    func finished(_ status: Int32?) {
        guard phase == .running else { return }
        phase = .exited(status)
        terminalLog.info("terminal: exited status=\(status.map(String.init) ?? "unknown", privacy: .public)")
        onExit?(status)
    }

    var statusLine: String {
        switch phase {
        case .ready: return "Starting…"
        case .running: return "Running. Type here when the command asks."
        case .exited(0?): return "Finished successfully. The terminal is read-only now."
        case .exited(let status?) where status < 0:
            return "Stopped by signal \(-status). The terminal is read-only now."
        case .exited(let status?): return "Exited with status \(status). The terminal is read-only now."
        case .exited(nil): return "Stopped. The terminal is read-only now."
        case .refused(let reason): return reason
        }
    }
}

/// A SwiftTerm view that forwards keystrokes only while its process runs.
final class FoTerminalNSView: LocalProcessTerminalView {
    var pending: (executable: URL, arguments: [String], environment: [String])?
    var onExit: ((Int32?) -> Void)?
    private var exited = false

    override func layout() {
        super.layout()
        // Start once the view has a size, so the pty gets real rows and columns.
        if let pending, bounds.width > 0, bounds.height > 0 {
            self.pending = nil
            startProcess(
                executable: pending.executable.path, args: pending.arguments,
                environment: pending.environment, execName: "fo",
                currentDirectory: FileManager.default.homeDirectoryForCurrentUser.path)
        }
    }

    /// Input after the process exits (or before it starts) goes nowhere.
    override func send(source: TerminalView, data: ArraySlice<UInt8>) {
        guard !exited, process?.running == true else { return }
        super.send(source: source, data: data)
    }

    override func processTerminated(_ source: LocalProcess, exitCode: Int32?) {
        markExited(exitCode.map { WaitStatus.exitCode(raw: $0) })
    }

    func markExited(_ status: Int32?) {
        guard !exited else { return }
        exited = true
        onExit?(status)
    }

    func stop() {
        guard !exited else { return }
        if process?.running == true {
            terminate()
        }
        markExited(nil)
    }
}

/// Hosts `FoTerminalNSView` in SwiftUI and starts the session's command once.
struct FoTerminalView: NSViewRepresentable {
    let session: FoTerminalSession
    /// Set by the view so the sheet's Stop button can end the process.
    let stopper: TerminalStopper

    func makeNSView(context: Context) -> FoTerminalNSView {
        let view = FoTerminalNSView(frame: NSRect(x: 0, y: 0, width: 640, height: 360))
        view.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        view.optionAsMetaKey = false
        view.onExit = { [weak session] status in
            DispatchQueue.main.async {
                MainActor.assumeIsolated { session?.finished(status) }
            }
        }
        stopper.view = view
        view.pending = session.prepare()
        return view
    }

    func updateNSView(_ view: FoTerminalNSView, context: Context) {}

    static func dismantleNSView(_ view: FoTerminalNSView, coordinator: ()) {
        // Closing the sheet ends the command; nothing outlives the view.
        view.stop()
    }
}

@MainActor
final class TerminalStopper {
    weak var view: FoTerminalNSView?

    func stop() {
        view?.stop()
    }
}

/// The sheet the Connectors pane shows: what will happen, the terminal, and its status.
struct TerminalSheet: View {
    let session: FoTerminalSession
    let close: () -> Void
    @State private var stopper = TerminalStopper()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(session.title)
                .font(.headline)
            if !session.explanation.isEmpty {
                Text(session.explanation)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if case .refused = session.phase {
                Label(session.statusLine, systemImage: "nosign")
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, minHeight: 120, alignment: .center)
            } else {
                FoTerminalView(session: session, stopper: stopper)
                    .frame(minWidth: 600, minHeight: 320)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                HStack(spacing: 6) {
                    if session.isRunning {
                        ProgressView().controlSize(.small)
                    } else if case .exited(let status) = session.phase {
                        Image(systemName: status == 0 ? "checkmark.circle.fill" : "xmark.octagon.fill")
                            .foregroundStyle(status == 0 ? .green : .red)
                    }
                    Text(session.statusLine)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            HStack {
                Text("Output stays in this window only; it is not saved.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer()
                if session.isRunning {
                    Button("Stop") { stopper.stop() }
                }
                Button(session.isRunning ? "Stop and Close" : "Close") {
                    stopper.stop()
                    close()
                }
                .keyboardShortcut(session.isRunning ? .cancelAction : .defaultAction)
            }
        }
        .padding(16)
        .frame(minWidth: 640)
    }
}
