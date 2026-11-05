import AppKit
import FOKit
import Observation
import SwiftUI

/// Settings > Connectors state. Keys go to `fo connect <provider>` on stdin and are cleared
/// from the field as soon as Save is pressed; the app keeps no copy and never logs one.
/// Connection state comes from the server's `/api/onboarding` and `/api/config` (masked);
/// the app never reads `secrets/` itself.
@MainActor
@Observable
final class ConnectorsModel {
    private(set) var states = ConnectorStates()
    private(set) var serverError: String?
    private(set) var busy: Set<String> = []
    /// Key fields by provider. Emptied on Save.
    var keys: [String: String] = [:]
    var edgarName = ""
    var edgarEmail = ""
    private var edgarPrefilled = false

    func refresh(api: APIClient?) async {
        guard let api else {
            serverError = "The server is not running, so connection states are unavailable."
            return
        }
        var failed = false
        if let onboarding = try? await api.onboarding() {
            states.onboarding = onboarding.providers
        } else {
            failed = true
        }
        if let config = try? await api.config() {
            states.config = config
        } else {
            failed = true
        }
        serverError = failed ? "The server did not report every connection state." : nil
        prefillEdgar()
        let summary = ConnectorCatalog.all.map { "\($0.id)=\(states.state($0))" }.joined(separator: " ")
        settingsLog.info("connectors: states \(summary, privacy: .public)")
    }

    private func prefillEdgar() {
        guard !edgarPrefilled, let agent = states.edgarUserAgent else { return }
        edgarPrefilled = true
        var words = agent.split(separator: " ").map(String.init)
        if let index = words.lastIndex(where: { $0.contains("@") }) {
            edgarEmail = words.remove(at: index)
        }
        edgarName = words.joined(separator: " ")
    }

    func state(_ connector: Connector) -> ConnectionState {
        states.state(connector)
    }

    func outcome(_ id: String) -> ConnectOutcome? {
        states.outcomes[id]
    }

    /// Save: `fo connect <provider>` with the key on stdin. The field is cleared first.
    func save(_ provider: String, office: String?, api: APIClient?) async {
        let raw = keys[provider] ?? ""
        keys[provider] = ""
        guard let arguments = ConnectCommand.save(provider) else { return }
        guard let stdin = ConnectCommand.stdin(forKey: raw) else {
            states.outcomes[provider] = ConnectOutcome(
                connected: false, succeeded: false,
                message: "Paste one API key: no spaces, at most 512 characters.")
            return
        }
        await run(provider, office: office, api: api, arguments, stdin: stdin, connected: true) {
            "Saved. \(ConnectorCatalog.label(provider)) accepted the key."
        }
    }

    /// Remove: `fo connect --remove <provider>`.
    func remove(_ provider: String, office: String?, api: APIClient?) async {
        guard let arguments = ConnectCommand.remove(provider) else { return }
        await run(provider, office: office, api: api, arguments, stdin: nil, connected: false) {
            "Removed."
        }
    }

    /// EDGAR: `fo connect edgar --user-agent "Name email"`.
    func saveEdgar(office: String?, api: APIClient?) async {
        let arguments = ConnectCommand.edgar(name: edgarName, email: edgarEmail)
        await run("edgar", office: office, api: api, arguments, stdin: nil, connected: true) {
            "Saved. SEC EDGAR requests will carry this name and email."
        }
    }

    /// The terminal's `fo auth` finished.
    func authFinished(_ provider: String, status: Int32?, api: APIClient?) async {
        if status == 0 {
            states.outcomes[provider] = ConnectOutcome(
                connected: true, succeeded: true, message: "fo auth \(provider) finished.")
        } else {
            states.outcomes[provider] = ConnectOutcome(
                connected: false, succeeded: false,
                message: "fo auth \(provider) did not finish; its reason is in the terminal.")
        }
        settingsLog.info(
            "connectors: auth \(provider, privacy: .public) exited \(status.map(String.init) ?? "unknown", privacy: .public)")
        await refresh(api: api)
    }

    private func run(
        _ provider: String, office: String?, api: APIClient?, _ arguments: [String], stdin: Data?,
        connected: Bool, success: () -> String
    ) async {
        busy.insert(provider)
        defer { busy.remove(provider) }
        switch await FoCommand.run(office: office, arguments, stdin: stdin) {
        case .success:
            states.outcomes[provider] = ConnectOutcome(connected: connected, succeeded: true, message: success())
            settingsLog.info("connectors: \(arguments[1] == "--remove" ? "removed" : "saved", privacy: .public) \(provider, privacy: .public)")
        case .failure(let error):
            states.outcomes[provider] = ConnectOutcome(connected: false, succeeded: false, message: error.message)
            settingsLog.info("connectors: \(provider, privacy: .public) refused (\(error.reason, privacy: .public))")
        }
        await refresh(api: api)
    }
}

/// Settings > Connectors: account providers through the embedded terminal, API keys through
/// native fields and `fo connect`, and the SEC EDGAR contact.
struct ConnectorsSettings: View {
    @Environment(AppState.self) private var state
    @State private var model = ConnectorsModel()
    @State private var terminal: FoTerminalSession?
    @State private var removing: Connector?

    var body: some View {
        Form {
            if state.officePath == nil {
                Section {
                    Text("Choose an office folder in General first; credentials live in its secrets folder.")
                        .foregroundStyle(.secondary)
                }
            } else if let error = model.serverError {
                Section {
                    Text(error).font(.caption).foregroundStyle(.secondary)
                }
            }
            Section("Accounts") {
                ForEach(ConnectorCatalog.all.filter { $0.kind == .account }) { connector in
                    accountRow(connector)
                }
            }
            Section {
                ForEach(ConnectorCatalog.all.filter { $0.kind == .key }) { connector in
                    keyRow(connector)
                }
            } header: {
                Text("Data and research keys")
            } footer: {
                Text(
                    "Save checks the key with one call to the provider, then fo connect stores it in the "
                        + "office's secrets folder. The key goes to fo on standard input; the app keeps no copy. "
                        + "The server does not yet report keys saved this way, so a row shows the last Save here."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Section("SEC EDGAR") {
                edgarRow
            }
        }
        .formStyle(.grouped)
        .disabled(state.officePath == nil)
        .task(id: state.api?.baseURL) {
            await model.refresh(api: state.api)
            #if DEBUG
            // Development walkthroughs without clicking: `-debugSaveSyntheticKey alphavantage`
            // saves a fixed, made-up key through the same path as the Save button, so the
            // CLI's refusal shows in the row and the log.
            if state.api != nil, let provider = UserDefaults.standard.string(forKey: "debugSaveSyntheticKey"),
                ConnectCommand.save(provider) != nil, model.outcome(provider) == nil
            {
                model.keys[provider] = "synthetic-walkthrough-key-0000"
                await model.save(provider, office: state.officePath, api: state.api)
                settingsLog.info(
                    "connectors: walkthrough save \(provider, privacy: .public): \(model.outcome(provider)?.message ?? "", privacy: .public)")
            }
            #endif
        }
        .sheet(item: $terminal) { session in
            TerminalSheet(session: session) { terminal = nil }
        }
        .confirmationDialog(
            "Remove the \(removing?.label ?? "") key?",
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            presenting: removing
        ) { connector in
            Button("Remove", role: .destructive) {
                Task { await model.remove(connector.id, office: state.officePath, api: state.api) }
            }
        } message: { connector in
            Text("fo connect --remove \(connector.id) deletes the stored key. Runs that need it stop working until you add one again.")
        }
    }

    // MARK: - Rows

    private func header(_ connector: Connector) -> some View {
        let connection = model.state(connector)
        return HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(connector.label)
                Text(connector.purpose)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Label(connection.label, systemImage: icon(connection))
                .font(.caption)
                .foregroundStyle(connection == .connected ? .green : .secondary)
        }
    }

    private func icon(_ state: ConnectionState) -> String {
        switch state {
        case .connected: return "checkmark.circle.fill"
        case .notConnected: return "circle"
        case .notReported: return "questionmark.circle"
        }
    }

    @ViewBuilder
    private func outcome(_ id: String) -> some View {
        if let outcome = model.outcome(id) {
            Text(outcome.message)
                .font(.caption)
                .foregroundStyle(outcome.succeeded ? Color.secondary : Color.red)
                .textSelection(.enabled)
        }
    }

    @ViewBuilder
    private func accountRow(_ connector: Connector) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            header(connector)
            Text(TerminalCommand.auth(connector.id).explanation)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(model.state(connector) == .connected ? "Reconnect…" : "Connect…") {
                    let session = FoTerminalSession(command: .auth(connector.id), office: state.officePath)
                    session.onExit = { status in
                        Task { await model.authFinished(connector.id, status: status, api: state.api) }
                    }
                    terminal = session
                }
                if let url = connector.signUp {
                    Link("Get access", destination: url).font(.caption)
                }
            }
            outcome(connector.id)
        }
    }

    @ViewBuilder
    private func keyRow(_ connector: Connector) -> some View {
        let busy = model.busy.contains(connector.id)
        let key = Binding(get: { model.keys[connector.id] ?? "" }, set: { model.keys[connector.id] = $0 })
        VStack(alignment: .leading, spacing: 6) {
            header(connector)
            HStack {
                SecureField("API key", text: key, prompt: Text("Paste the \(connector.label) API key"))
                    .labelsHidden()
                    .onSubmit { save(connector) }
                Button("Save") { save(connector) }
                    .disabled(key.wrappedValue.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                Button("Remove…") { removing = connector }
                    .disabled(busy || model.state(connector) == .notConnected)
                if busy {
                    ProgressView().controlSize(.small)
                }
            }
            HStack {
                outcome(connector.id)
                Spacer()
                if let url = connector.signUp {
                    Link("Get a key", destination: url).font(.caption)
                }
            }
        }
    }

    private var edgarRow: some View {
        let connector = ConnectorCatalog.connector("edgar")!
        let busy = model.busy.contains("edgar")
        return VStack(alignment: .leading, spacing: 6) {
            header(connector)
            HStack {
                TextField("Name", text: $model.edgarName, prompt: Text("Name"))
                    .labelsHidden()
                TextField("Email", text: $model.edgarEmail, prompt: Text("email@example.com"))
                    .labelsHidden()
                Button("Save") {
                    Task { await model.saveEdgar(office: state.officePath, api: state.api) }
                }
                .disabled(
                    model.edgarName.trimmingCharacters(in: .whitespaces).isEmpty
                        || !model.edgarEmail.contains("@") || busy)
                Button("Remove") {
                    Task { await model.remove("edgar", office: state.officePath, api: state.api) }
                }
                .disabled(busy || model.state(connector) == .notConnected)
            }
            Text("Saved with fo connect edgar --user-agent \"Name email\" into office.toml.")
                .font(.caption)
                .foregroundStyle(.secondary)
            outcome("edgar")
        }
    }

    private func save(_ connector: Connector) {
        Task { await model.save(connector.id, office: state.officePath, api: state.api) }
    }
}
