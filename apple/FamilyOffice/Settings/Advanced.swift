import FOKit
import Observation
import SwiftUI

/// One `office.toml` setting the Advanced pane edits through `fo config set`.
struct ConfigField: Identifiable {
    /// One value a choice field can store, with what it means.
    struct Option: Identifiable {
        let value: String
        let label: String
        let help: String

        var id: String { value }
    }

    let key: String
    let label: String
    let help: String
    /// What the server uses when the key is unset: shown as the prompt of a text field, and
    /// the selected value of a choice or switch.
    let placeholder: String
    /// The server reads this key only at start, so a change restarts it.
    let restarts: Bool
    /// The values a choice field offers; empty for a text field or a switch.
    var options: [Option] = []

    var id: String { key }

    /// What advisors may do on the web, in every chat. The page's own switch can still turn
    /// web off for one chat.
    static let web = ConfigField(
        key: "serve.web", label: "Advisors may use the web",
        help: "", placeholder: "on", restarts: false,
        options: [
            Option(
                value: "on", label: "In every chat",
                help:
                    "Advisors can search and read the web in any chat, including ones that read your household data. Each search and site is listed in the chat, and a search that carries an account or Social Security number is refused."
            ),
            Option(
                value: "isolated", label: "Only without household data",
                help:
                    "Web works only in chats set to read no household data, so nothing from the office can reach a search or a URL. Advisors that read your accounts answer without looking anything up."
            ),
            Option(
                value: "off", label: "Never",
                help: "No advisor can search or read the web."),
        ])

    static let autoSync = ConfigField(
        key: "serve.auto_sync", label: "Sync accounts automatically",
        help:
            "While the app is open it refreshes balances, positions and transactions when they are older than the interval below. It waits for advisors to finish first.",
        placeholder: "true", restarts: false)

    static let autoSyncHours = ConfigField(
        key: "serve.auto_sync_hours", label: "Sync interval (hours)",
        help: "How old account data may get before the app syncs on its own.",
        placeholder: "6", restarts: false)

    static let advanced: [ConfigField] = [
        ConfigField(
            key: "serve.parallel_runs", label: "Advisors at once",
            help: "How many advisors may answer at the same time, from 1 to 8.",
            placeholder: "3", restarts: false),
        ConfigField(
            key: "serve.max_budget_usd", label: "Reply budget (USD)",
            help: "The most one advisor reply may spend.", placeholder: "2.0", restarts: false),
        ConfigField(
            key: "serve.run_timeout_minutes", label: "Reply timeout (minutes)",
            help: "A reply still going after this long is stopped.", placeholder: "30", restarts: false),
        ConfigField(
            key: "serve.keep_runs", label: "Chats kept",
            help: "Finished chats kept in the history, across every advisor.", placeholder: "300",
            restarts: false),
        ConfigField(
            key: "serve.web_fetch_cap", label: "Web fetch cap",
            help: "The most web pages one reply may fetch.", placeholder: "20", restarts: false),
        ConfigField(
            key: "serve.port", label: "Port",
            help: "Used while phone access over Tailscale is on; otherwise the app picks a free port each launch.",
            placeholder: "4790", restarts: true),
    ]

    static let all: [ConfigField] = [web, autoSync, autoSyncHours] + advanced
}

/// Loads and saves the Advanced fields. Every write is `fo config set KEY VALUE`; a refusal
/// shows the CLI's own message under the field.
@MainActor
@Observable
final class ConfigFieldsModel {
    let fields: [ConfigField]
    var text: [String: String] = [:]
    private(set) var stored: [String: String] = [:]
    private(set) var errors: [String: String] = [:]
    private(set) var notes: [String: String] = [:]
    /// Keys this version of `fo config set` does not accept.
    private(set) var unsupported: Set<String> = []
    private(set) var busy: Set<String> = []
    private(set) var loaded = false

    init(fields: [ConfigField]) {
        self.fields = fields
    }

    func load(office: String?) async {
        for field in fields {
            switch await FoCommand.configGet(office: office, field.key) {
            case .success(let value):
                let current = value?.fieldText ?? ""
                stored[field.key] = current
                text[field.key] = current
                errors[field.key] = nil
            case .failure(let error) where error.reason == "invalid_key":
                unsupported.insert(field.key)
            case .failure(let error):
                errors[field.key] = error.message
            }
        }
        loaded = true
        settingsLog.info(
            "advanced: loaded=\(self.stored.count, privacy: .public) unsupported=\(self.unsupported.sorted().joined(separator: ","), privacy: .public) errors=\(self.errors.count, privacy: .public)"
        )
    }

    func isDirty(_ field: ConfigField) -> Bool {
        (text[field.key] ?? "") != (stored[field.key] ?? "")
    }

    /// What a choice or switch shows: the stored value, else what the server uses unset.
    func value(_ field: ConfigField) -> String {
        let current = text[field.key] ?? ""
        return current.isEmpty ? field.placeholder : current
    }

    /// Writes one field; returns true when `fo config set` accepted it.
    @discardableResult
    func save(_ field: ConfigField, office: String?) async -> Bool {
        let value = (text[field.key] ?? "").trimmingCharacters(in: .whitespaces)
        busy.insert(field.key)
        defer { busy.remove(field.key) }
        notes[field.key] = nil
        switch await FoCommand.configSet(office: office, field.key, value) {
        case .success(let saved):
            let current = saved.fieldText
            stored[field.key] = current
            text[field.key] = current
            errors[field.key] = nil
            notes[field.key] = field.restarts ? "Saved. Restarting the server…" : "Saved."
            return true
        case .failure(let error):
            errors[field.key] = error.message
            settingsLog.info(
                "advanced: \(field.key, privacy: .public) refused (\(error.reason, privacy: .public))")
            return false
        }
    }
}

/// Settings > Advanced: web access, automatic sync, and the limits on advisor replies.
struct AdvancedSettings: View {
    @Environment(AppState.self) private var state
    @State private var model = ConfigFieldsModel(fields: ConfigField.all)

    var body: some View {
        Form {
            if state.officePath == nil {
                Section {
                    Text("Choose an office folder in General first; these settings live in its office.toml.")
                        .foregroundStyle(.secondary)
                }
            }
            Section("Web access") {
                choice(ConfigField.web)
            }
            Section("Account sync") {
                toggle(ConfigField.autoSync)
                row(ConfigField.autoSyncHours)
                    .disabled(model.value(ConfigField.autoSync) != "true")
            }
            Section {
                ForEach(ConfigField.advanced) { field in
                    row(field)
                }
            } header: {
                Text("Limits")
            } footer: {
                Text("Saved with fo config set into the office's office.toml; the app never edits the file itself.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .disabled(state.officePath == nil)
        .task(id: state.officePath) {
            await model.load(office: state.officePath)
        }
    }

    /// A picker that saves as soon as a value is chosen, with what that value means below.
    @ViewBuilder
    private func choice(_ field: ConfigField) -> some View {
        let unsupported = model.unsupported.contains(field.key)
        let current = model.value(field)
        VStack(alignment: .leading, spacing: 4) {
            Picker(
                field.label,
                selection: Binding(
                    get: { current },
                    set: { chosen in
                        model.text[field.key] = chosen
                        save(field)
                    })
            ) {
                ForEach(field.options) { option in
                    Text(option.label).tag(option.value)
                }
            }
            .disabled(unsupported || model.busy.contains(field.key))
            status(field, help: field.options.first { $0.value == current }?.help ?? field.help)
        }
    }

    /// A switch that saves as soon as it is flipped.
    @ViewBuilder
    private func toggle(_ field: ConfigField) -> some View {
        let unsupported = model.unsupported.contains(field.key)
        VStack(alignment: .leading, spacing: 4) {
            Toggle(
                field.label,
                isOn: Binding(
                    get: { model.value(field) == "true" },
                    set: { on in
                        model.text[field.key] = on ? "true" : "false"
                        save(field)
                    })
            )
            .disabled(unsupported || model.busy.contains(field.key))
            status(field, help: field.help)
        }
    }

    /// The line under a field: why it is unavailable, the CLI's refusal, "Saved.", or its help.
    @ViewBuilder
    private func status(_ field: ConfigField, help: String) -> some View {
        if model.unsupported.contains(field.key) {
            Text("This version of fo cannot set \(field.key) yet.")
                .font(.caption)
                .foregroundStyle(.secondary)
        } else if let error = model.errors[field.key] {
            Text(error)
                .font(.caption)
                .foregroundStyle(.red)
        } else {
            Text(help)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func row(_ field: ConfigField) -> some View {
        let unsupported = model.unsupported.contains(field.key)
        VStack(alignment: .leading, spacing: 4) {
            LabeledContent(field.label) {
                HStack {
                    TextField(
                        field.label,
                        text: Binding(
                            get: { model.text[field.key] ?? "" },
                            set: { model.text[field.key] = $0 }),
                        prompt: Text(field.placeholder)
                    )
                    .labelsHidden()
                    .multilineTextAlignment(.trailing)
                    .frame(width: 120)
                    .onSubmit { save(field) }
                    Button("Set") { save(field) }
                        .disabled(!model.isDirty(field) || model.busy.contains(field.key))
                }
            }
            .disabled(unsupported)
            if unsupported {
                Text("This version of fo cannot set \(field.key) yet.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if let error = model.errors[field.key] {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else if let note = model.notes[field.key] {
                Text(note)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text(field.help)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func save(_ field: ConfigField) {
        Task {
            let saved = await model.save(field, office: state.officePath)
            if saved, field.restarts {
                state.restartServer()
            }
        }
    }
}
