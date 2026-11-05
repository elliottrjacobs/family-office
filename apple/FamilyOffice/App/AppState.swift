import AppKit
import FOKit
import Foundation
import Observation
import WebKit

/// App-wide state: the server's lifecycle, the current handshake, the office path, and the
/// banner shown over the web view.
@MainActor
@Observable
final class AppState {
    enum ServerState: Equatable {
        case idle
        case starting
        case running
        case restarting(attempt: Int, delay: Int)
        case failed(String)
        case stopped
    }

    /// `UserDefaults` key for the chosen office folder.
    static let officePathKey = "officePath"
    /// `UserDefaults` key for "Allow phone access over Tailscale" (`fo serve --remote`).
    static let phoneAccessKey = "allowPhoneAccess"

    private(set) var serverState: ServerState = .idle
    /// The live server's handshake. Its token stays in memory and is only used by the web view.
    private(set) var handshake: Handshake?
    /// Bumped for every new handshake and every manual reload; the web view reloads on change.
    private(set) var pageGeneration = 0
    private(set) var officePath: String?
    /// The setup dialog on screen, if any.
    var setup: SetupModel?
    /// Runs the server with `--remote` on the configured port, for `tailscale serve`.
    private(set) var phoneAccess: Bool

    /// Reachability of the status route, probed once the web view holds the session cookie.
    private(set) var reachability: Reachability?
    private(set) var api: APIClient?

    /// Status, runs and devices for the menu bar, polled every thirty seconds.
    let monitor = OfficeMonitor()
    /// The keep-awake assertion; it follows the paired-device count.
    let power = Power()
    /// Launch at login.
    let loginItem = LoginItem()
    /// The `/usr/local/bin/fo` link, verified on launch.
    let commandLineTool = CommandLineTool()

    /// One non-persistent website data store per launch, so the session cookie dies with the app.
    @ObservationIgnored let websiteDataStore = WKWebsiteDataStore.nonPersistent()
    @ObservationIgnored private let server = ServerProcess()
    @ObservationIgnored private let primer = SessionPrimer()
    @ObservationIgnored private let defaults = UserDefaults.standard

    init() {
        officePath = defaults.string(forKey: Self.officePathKey).flatMap { $0.isEmpty ? nil : $0 }
        phoneAccess = UserDefaults.standard.bool(forKey: Self.phoneAccessKey)
        server.onEvent = { [weak self] event in self?.handle(event) }
        monitor.onDevices = { [weak self] devices in
            self?.power.update(deviceCount: devices.count)
        }
    }

    /// The menu bar's first line: the office folder, shortened with a tilde.
    var officeTitle: String {
        guard let officePath else { return "No office folder chosen" }
        return (officePath as NSString).abbreviatingWithTildeInPath
    }

    /// The menu bar's server line while the server is not running normally, else nil.
    var serverLine: String? {
        switch serverState {
        case .running: return nil
        case .idle: return officePath == nil ? "Choose an office folder to start" : "Server not started"
        case .starting: return "Starting the server…"
        case .restarting(let attempt, _): return "Server restarting (attempt \(attempt))"
        case .failed: return "Server stopped with an error"
        case .stopped: return "Server stopped"
        }
    }

    var serverRunning: Bool { server.isRunning }

    /// The rolling in-memory server log (last 500 lines, tokens redacted).
    var serverLog: [String] { server.log.lines }

    /// Text over the web view, or nil when everything is fine.
    var banner: String? {
        switch serverState {
        case .idle, .running:
            if let reachability, handshake != nil, !reachability.reachable, reachability.lastSeen != nil {
                return "The server is not responding."
            }
            return nil
        case .starting:
            return handshake == nil ? "Starting the server…" : nil
        case .restarting(let attempt, let delay):
            return "The server stopped unexpectedly. Restarting in \(delay) s (attempt \(attempt) of \(ServerProcess.maxRestarts))."
        case .failed(let message):
            return message
        case .stopped:
            return "The server is stopped."
        }
    }

    var bannerIsError: Bool {
        if case .failed = serverState { return true }
        return false
    }

    func launch() {
        Task {
            // The server should run the CLIs the app finds, so look before the first start.
            await detectEngines(restart: false)
            openSetup(manual: false)
            if officePath != nil {
                startServer()
            }
        }
    }

    /// Opens the setup dialog: at launch only when `SetupVersion` says steps are due, from
    /// Help > Set Up Family Office… always. A stored office with `office.toml` is the
    /// existing profile, which starts at the engine step.
    func openSetup(manual: Bool) {
        guard setup == nil else { return }
        let profile = SetupProfile.detect(officePath: officePath) { FileManager.default.fileExists(atPath: $0) }
        let steps = SetupFlow.steps(
            profile: profile, stored: SetupVersion.stored, current: SetupVersion.current, manual: manual,
            newSince: SetupVersion.newSince)
        guard !steps.isEmpty else {
            setupLog.info("setup: not shown; version \(SetupVersion.current, privacy: .public) is finished")
            return
        }
        setup = SetupModel(flow: SetupFlow(steps: steps, profile: profile), manual: manual)
    }

    func closeSetup() {
        setup = nil
    }

    /// Finds `claude` and `codex` the way Settings > Engines does and names them in the
    /// server's environment.
    func detectEngines(restart: Bool = true) async {
        let detector = EngineDetector()
        async let claude = detector.locate(.claude)
        async let codex = detector.locate(.codex)
        var found: [EngineKind: CLILocation] = [:]
        found[.claude] = await claude
        found[.codex] = await codex
        applyEngineLocations(found, restart: restart)
    }

    /// Called with what the Engines pane detected. A change restarts a running server so its
    /// next advisor run uses the CLI found now.
    func applyEngineLocations(_ locations: [EngineKind: CLILocation], restart: Bool = true) {
        let environment = EngineExecutables.environment(locations)
        guard environment != ServerProcess.engineExecutables else { return }
        ServerProcess.engineExecutables = environment
        let names = environment.keys.sorted().joined(separator: ",")
        settingsLog.info("engines: server environment names \(names.isEmpty ? "none" : names, privacy: .public)")
        if restart, server.isRunning {
            restartServer()
        }
    }

    func startServer() {
        serverState = .starting
        server.start(office: officePath, remote: phoneAccess && officePath != nil)
    }

    func restartServer() {
        Task {
            await server.stop()
            startServer()
        }
    }

    /// Turns phone access on or off and restarts the server. `--remote` needs
    /// `[serve] tailnet_name`, so turning it on without one is refused with the reason.
    func setPhoneAccess(_ on: Bool) async -> String? {
        if on {
            guard officePath != nil else { return "Choose an office folder first." }
            switch await FoCommand.configGet(office: officePath, "serve.tailnet_name") {
            case .success(let value?) where !value.fieldText.isEmpty:
                break
            case .success:
                return "Set this Mac's tailnet name in Devices first."
            case .failure(let error):
                return error.message
            }
        }
        phoneAccess = on
        defaults.set(on, forKey: Self.phoneAccessKey)
        restartServer()
        return nil
    }

    func shutdown() async {
        reachability?.stop()
        monitor.stop()
        primer.cancel()
        power.release()
        await server.stop()
        serverState = .stopped
    }

    func reloadPage() {
        guard handshake != nil else { return }
        pageGeneration += 1
    }

    /// File > Choose Office Folder…: switch to another folder without the setup dialog.
    func chooseOffice() {
        let panel = NSOpenPanel()
        panel.title = "Choose the office folder"
        panel.message = "Choose an existing office folder, or create an empty folder for a new office."
        panel.prompt = "Use Folder"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        setOffice(url.path)
    }

    func setOffice(_ path: String?) {
        officePath = path
        if let path {
            defaults.set(path, forKey: Self.officePathKey)
        } else {
            defaults.removeObject(forKey: Self.officePathKey)
        }
        if server.isRunning {
            restartServer()
        } else {
            startServer()
        }
    }

    /// Called by the web view after a page from the server finishes loading.
    func pageLoaded(cookies: [HTTPCookie]) {
        guard let handshake else { return }
        if api == nil || api?.baseURL != handshake.baseURL {
            reachability?.stop()
            let client = APIClient(handshake: handshake, timeout: 3)
            api = client
            reachability = Reachability(client: client)
        }
        api?.setCookies(cookies)
        reachability?.start()
        monitor.attach(api)
    }

    /// Polls the routes now, for panes that just changed something.
    func refreshMonitor() async {
        await monitor.refresh()
    }

    private func handle(_ event: ServerProcess.Event) {
        switch event {
        case .handshake(let value):
            handshake = value
            serverState = .running
            pageGeneration += 1
            // The menu bar needs the cookie even while the main window is closed.
            primer.prime(value, store: websiteDataStore) { [weak self] cookies in
                self?.pageLoaded(cookies: cookies)
            }
        case .restarting(let attempt, let delay):
            handshake = nil
            reachability?.stop()
            monitor.stop()
            serverState = .restarting(attempt: attempt, delay: delay)
        case .starting:
            serverState = .starting
        case .failed(let message):
            handshake = nil
            reachability?.stop()
            monitor.stop()
            serverState = .failed(message)
        case .stopped:
            handshake = nil
            reachability?.stop()
            monitor.stop()
            serverState = .stopped
        }
    }
}
