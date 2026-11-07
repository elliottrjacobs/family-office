import AppKit
import FOKit
import Observation
import os

let setupLog = Logger(subsystem: "com.familyoffice.app", category: "setup")

/// The setup dialog's state (plan R7 to R10): the step list and position from
/// `FOKit.SetupFlow`, the profile, the choices patched per step, and the office step's
/// create-or-open flow.
///
/// Nothing here writes office files: the office is created by `fo setup --offline` in the
/// embedded terminal, engine defaults by `fo config set`, accounts by `fo auth`, keys by
/// `fo connect`, and pairing through the server's routes, each through the same models the
/// Settings panes use.
@MainActor
@Observable
final class SetupModel: Identifiable {
    enum OfficeMode: String {
        case create
        case open
    }

    let id = UUID()
    private(set) var flow: SetupFlow
    /// Opened from Help > Set Up Family Office… rather than at launch.
    let manual: Bool

    // Office step.
    var officeMode = OfficeMode.create
    private(set) var parentFolder: URL?
    var officeName = "family-office"
    private(set) var setupSession: FoTerminalSession?
    private(set) var officeError: String?
    /// The office the dialog created or opened, once `fo setup` finished or the folder was
    /// chosen; the server's onboarding state then decides whether the step is complete.
    private(set) var chosenOffice: String?
    /// The server reports an office (its onboarding state is past `no_office` and
    /// `uninitialized_path`).
    private(set) var officeReady = false
    private(set) var officeState: String?

    // The Settings panes' models, so each step can summarize what was done.
    let engines = EnginesModel()
    let accounts = ConnectorsModel()
    let research = ConnectorsModel()
    var syncSession: FoTerminalSession?
    private(set) var firstSyncFinished = false

    init(flow: SetupFlow, manual: Bool) {
        self.flow = flow
        self.manual = manual
        setupLog.info(
            "setup: opened profile=\(flow.profile.rawValue, privacy: .public) manual=\(manual, privacy: .public) steps=\(flow.steps.map(\.rawValue).joined(separator: ","), privacy: .public)"
        )
    }

    var profile: SetupProfile { flow.profile }
    var step: SetupStep { flow.current }

    // MARK: - Buttons

    var primaryLabel: String {
        switch step {
        case .welcome: return "Get Started"
        case .done: return "Open Family Office"
        default: return "Continue"
        }
    }

    var skipLabel: String { step == .engine ? "Later" : "Skip" }

    var primaryEnabled: Bool {
        switch step {
        case .office: return officeReady
        default: return true
        }
    }

    /// The primary button: records the step's choice and moves on, or finishes.
    func primary(state: AppState) {
        guard primaryEnabled else { return }
        switch step {
        case .welcome:
            flow.complete()
        case .office:
            flow.complete(officeSummary)
        case .engine:
            flow.complete(engineSummary)
        case .accounts:
            if let line = accountsSummary { flow.complete(line) } else { flow.skip() }
        case .research:
            if let line = researchSummary { flow.complete(line) } else { flow.skip() }
        case .phone:
            let paired = state.monitor.devices?.count ?? 0
            if paired > 0 {
                flow.complete(paired == 1 ? "1 phone paired" : "\(paired) phones paired")
            } else {
                flow.skip()
            }
        case .done:
            finish(state: state)
            return
        }
        logStep()
    }

    func skip() {
        guard flow.skip() else { return }
        logStep()
    }

    func back() {
        flow.back()
        logStep()
    }

    /// Stores the setup version and closes the dialog.
    func finish(state: AppState) {
        SetupVersion.markFinished()
        setupLog.info("setup: finished version=\(SetupVersion.current, privacy: .public)")
        state.closeSetup()
        state.reloadPage()
    }

    /// Return in the dialog: the primary action unless focus is in a field or the terminal.
    func handleReturn(focus: SetupFocus, state: AppState) -> Bool {
        guard SetupFlow.returnAdvances(focus: focus, primaryEnabled: primaryEnabled) else { return false }
        primary(state: state)
        return true
    }

    private func logStep() {
        let outcome: String
        switch flow.outcomes[flow.steps[max(flow.index - 1, 0)]] {
        case .completed?: outcome = "completed"
        case .skipped?: outcome = "skipped"
        case nil: outcome = "passed"
        }
        setupLog.info(
            "setup: step=\(self.step.rawValue, privacy: .public) index=\(self.flow.index, privacy: .public)/\(self.flow.steps.count, privacy: .public) previous=\(outcome, privacy: .public)"
        )
    }

    // MARK: - Office step

    /// The folder `fo setup` will create: the parent folder plus the name.
    var newOfficePath: String? {
        guard let parentFolder else { return nil }
        let name = officeName.trimmingCharacters(in: .whitespaces)
        guard Self.validName(name) else { return nil }
        return parentFolder.appendingPathComponent(name).path
    }

    static func validName(_ name: String) -> Bool {
        !name.isEmpty && !name.hasPrefix(".") && !name.contains("/") && !name.contains(":")
            && name.count <= 255
    }

    func chooseParent() {
        let panel = NSOpenPanel()
        panel.title = "Choose where to create the office"
        panel.message = "Family Office creates a new folder here."
        panel.prompt = "Choose"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = parentFolder ?? FileManager.default.homeDirectoryForCurrentUser
        guard panel.runModal() == .OK, let url = panel.url else { return }
        setParent(url)
    }

    func setParent(_ url: URL) {
        parentFolder = url
        officeError = nil
    }

    /// Runs `fo setup PATH --offline` in the embedded terminal. On success the path becomes
    /// the office and the server restarts on it.
    func create(state: AppState) {
        officeError = nil
        guard let path = newOfficePath else {
            officeError = "Choose a folder and a name without slashes."
            return
        }
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory) {
            let empty = (try? FileManager.default.contentsOfDirectory(atPath: path))?.isEmpty ?? false
            guard isDirectory.boolValue, empty else {
                officeError = "Something named \(officeName) already exists there. Choose another name."
                return
            }
        }
        let session = FoTerminalSession(command: .setupOffline, office: path)
        session.onExit = { [weak self, weak state] status in
            guard let self, let state else { return }
            setupLog.info("setup: fo setup exited status=\(status.map(String.init) ?? "unknown", privacy: .public)")
            if status == 0 {
                self.useOffice(path, mode: .create, state: state)
            } else {
                self.officeError = "fo setup did not finish; its reason is in the terminal above."
            }
        }
        setupSession = session
        setupLog.info("setup: creating an office with fo setup --offline")
    }

    /// Open existing: a folder that holds `office.toml`.
    func openExisting(state: AppState) {
        officeError = nil
        let panel = NSOpenPanel()
        panel.title = "Open an existing office"
        panel.message = "Choose the folder that contains office.toml."
        panel.prompt = "Open"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard FileManager.default.fileExists(atPath: url.appendingPathComponent("office.toml").path) else {
            officeError = "That folder has no office.toml. Choose the office folder itself, or create a new office."
            setupLog.info("setup: chosen folder has no office.toml")
            return
        }
        useOffice(url.path, mode: .open, state: state)
    }

    private func useOffice(_ path: String, mode: OfficeMode, state: AppState) {
        chosenOffice = path
        officeMode = mode
        officeReady = false
        state.setOffice(path)
        setupLog.info("setup: office \(mode == .create ? "created" : "opened", privacy: .public); restarting the server")
    }

    /// Asks the server whether it sees the office now. Called whenever its session changes.
    func checkOffice(api: APIClient?, officePath: String?) async {
        guard let chosenOffice, officePath == chosenOffice, let api else { return }
        guard let onboarding = try? await api.onboarding() else { return }
        officeState = onboarding.state
        let ready = onboarding.office != nil && !["no_office", "uninitialized_path"].contains(onboarding.state)
        if ready != officeReady {
            officeReady = ready
            setupLog.info("setup: server onboarding state=\(onboarding.state, privacy: .public) officeReady=\(ready, privacy: .public)")
        }
    }

    private var officeSummary: String {
        let name = chosenOffice.map { ($0 as NSString).abbreviatingWithTildeInPath } ?? "the office"
        return officeMode == .create ? "Office created at \(name)" : "Office opened at \(name)"
    }

    // MARK: - Summaries

    private var engineSummary: String {
        let engine = EngineKind(rawValue: engines.defaultEngine) ?? .claude
        let installed = engines.detections[engine]?.installed ?? false
        return "Default engine: \(engine.label)\(installed ? "" : " (not installed yet)")"
    }

    private var accountsSummary: String? {
        let connected = ConnectorCatalog.all.filter { $0.kind == .account && accounts.state($0) == .connected }
        guard !connected.isEmpty else { return nil }
        let names = connected.map(\.label).joined(separator: " and ")
        return "Connected \(names)\(firstSyncFinished ? ", first sync finished" : "")"
    }

    var anyAccountConnected: Bool {
        ConnectorCatalog.all.contains { $0.kind == .account && accounts.state($0) == .connected }
    }

    private var researchSummary: String? {
        let count = ConnectorCatalog.all.filter { $0.kind == .key && research.state($0) == .connected }.count
        guard count > 0 else { return nil }
        return count == 1 ? "1 research key" : "\(count) research keys"
    }

    // MARK: - Accounts step

    func runFirstSync(office: String?) {
        let session = FoTerminalSession(command: .sync, office: office)
        session.onExit = { [weak self] status in
            if status == 0 { self?.firstSyncFinished = true }
        }
        syncSession = session
    }
}
