import FOKit
import Observation
import SwiftUI

/// One `office.toml` setting the Advanced pane edits through `fo config set`.
struct ConfigField: Identifiable {
    let key: String
    let label: String
    let help: String
    /// What the server uses when the key is unset.
    let placeholder: String
    /// The server reads this key only at start, so a change restarts it.
    let restarts: Bool

    var id: String { key }

    static let advanced: [ConfigField] = [
        ConfigField(
            key: "serve.port", label: "Port",
            help: "Used while phone access over Tailscale is on; otherwise the app picks a free port each launch.",
            placeholder: "4790", restarts: true),
        ConfigField(
            key: "serve.max_budget_usd", label: "Run budget (USD)",
            help: "The most one advisor run may spend.", placeholder: "2.0", restarts: false),
        ConfigField(
            key: "serve.run_timeout_minutes", label: "Run timeout (minutes)",
            help: "A run still going after this long is stopped.", placeholder: "30", restarts: false),
        ConfigField(
            key: "serve.keep_runs", label: "Runs kept",
            help: "Finished runs kept in the run history.", placeholder: "50", restarts: false),
        ConfigField(
            key: "serve.web_fetch_cap", label: "Web fetch cap",
            help: "The most web pages one run may fetch.", placeholder: "not set", restarts: false),
    ]
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

/// Settings > Advanced: port, run caps, retention and the web fetch cap.
struct AdvancedSettings: View {
    @Environment(AppState.self) private var state
    @State private var model = ConfigFieldsModel(fields: ConfigField.advanced)

    var body: some View {
        Form {
            if state.officePath == nil {
                Section {
                    Text("Choose an office folder in General first; these settings live in its office.toml.")
                        .foregroundStyle(.secondary)
                }
            }
            Section {
                ForEach(model.fields) { field in
                    row(field)
                }
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
