import AppKit
import FOKit
import Observation
import SwiftUI

/// Detection, the server's verdict, and the per-engine defaults for Settings > Engines.
/// Every default is written with `fo config set serve.engines.…`; the app never edits
/// office.toml.
@MainActor
@Observable
final class EnginesModel {
    static let otherModel = "__other__"

    private(set) var detections: [EngineKind: EngineDetection] = [:]
    private(set) var detecting = false
    private(set) var runner: RunnerStatus?
    private(set) var catalog: ModelCatalog?
    /// Why the server's status or catalog could not be read, when it could not.
    private(set) var serverError: String?

    var defaultEngine = EngineKind.claude.rawValue
    /// The model picker's selection per engine: a catalog id or `otherModel`.
    var modelChoice: [EngineKind: String] = [:]
    /// The "Other…" free-text model per engine.
    var otherModel: [EngineKind: String] = [:]
    var effort: [EngineKind: String] = [:]
    var budget: [EngineKind: String] = [:]
    var enabled: [EngineKind: Bool] = [:]

    /// Messages under a field, by config key: the CLI's refusal or "Saved."
    private(set) var errors: [String: String] = [:]
    private(set) var notes: [String: String] = [:]
    private(set) var busy: Set<String> = []
    private(set) var stored: [String: String] = [:]

    private let detector = EngineDetector()

    func detect() async {
        detecting = true
        defer { detecting = false }
        async let claude = detector.detect(.claude)
        async let codex = detector.detect(.codex)
        let found = await [claude, codex]
        for detection in found {
            detections[detection.engine] = detection
        }
        let summary = found.map { detection in
            guard let location = detection.location else { return "\(detection.engine.rawValue)=missing" }
            let version = detection.version == nil ? "no-version" : "version"
            let signIn: String
            switch detection.signIn {
            case .signedIn: signIn = "signed-in"
            case .signedOut: signIn = "signed-out"
            case .unknown: signIn = "sign-in-unknown"
            }
            return "\(detection.engine.rawValue)=\(location.source.rawValue)/\(version)/\(signIn)"
        }.joined(separator: " ")
        settingsLog.info("engines: detected \(summary, privacy: .public)")
    }

    func loadServer(api: APIClient?) async {
        guard let api else {
            runner = nil
            catalog = nil
            serverError = "The server is not running, so its engine status and defaults are unavailable."
            return
        }
        do {
            let runner = try await api.runner()
            self.runner = runner
            serverError = nil
            let summary = runner.engines.map { "\($0.name)=\($0.usable ? "usable" : $0.reason ?? "unusable")" }
                .joined(separator: " ")
            settingsLog.info("engines: server \(summary, privacy: .public)")
        } catch {
            runner = nil
            serverError = "The server did not report engine status."
        }
        do {
            let catalog = try await api.models()
            self.catalog = catalog
            apply(catalog)
            settingsLog.info(
                "engines: catalog default=\(catalog.default, privacy: .public) models=\(catalog.engines.values.map(\.models.count).reduce(0, +), privacy: .public)")
        } catch {
            catalog = nil
            serverError = serverError ?? "The server did not report its model list."
        }
    }

    private func apply(_ catalog: ModelCatalog) {
        defaultEngine = catalog.default
        stored["serve.engines.default"] = catalog.default
        for engine in EngineKind.allCases {
            guard let defaults = catalog.defaults[engine.rawValue] else { continue }
            let known = models(engine).contains { $0.id == defaults.model }
            modelChoice[engine] = known ? defaults.model : Self.otherModel
            otherModel[engine] = known ? "" : defaults.model
            effort[engine] = defaults.effort
            budget[engine] = JSONValue.number(defaults.maxBudgetUsd).fieldText
            enabled[engine] = defaults.enabled
            stored[key(engine, "model")] = defaults.model
            stored[key(engine, "max_budget_usd")] = budget[engine]
        }
    }

    func models(_ engine: EngineKind) -> [ModelCatalog.Model] {
        catalog?.engines[engine.rawValue]?.models ?? []
    }

    func efforts(_ engine: EngineKind) -> [String] {
        catalog?.engines[engine.rawValue]?.efforts ?? ["low", "medium", "high"]
    }

    func key(_ engine: EngineKind, _ field: String) -> String {
        "serve.engines.\(engine.rawValue).\(field)"
    }

    func isDirty(_ key: String, _ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespaces)
        return !trimmed.isEmpty && trimmed != (stored[key] ?? "")
    }

    /// `fo config set KEY VALUE`, then the server's status again (an engine turned off
    /// changes `usable`). Returns true when the CLI accepted the value.
    @discardableResult
    func set(_ key: String, _ value: String, office: String?, api: APIClient?) async -> Bool {
        let value = value.trimmingCharacters(in: .whitespaces)
        busy.insert(key)
        defer { busy.remove(key) }
        notes[key] = nil
        switch await FoCommand.configSet(office: office, key, value) {
        case .success(let saved):
            stored[key] = saved.fieldText
            errors[key] = nil
            notes[key] = "Saved."
            settingsLog.info("engines: set \(key, privacy: .public)")
            await loadServer(api: api)
            return true
        case .failure(let error):
            errors[key] = error.message
            settingsLog.info("engines: \(key, privacy: .public) refused (\(error.reason, privacy: .public))")
            // Show what is really stored again.
            await loadServer(api: api)
            return false
        }
    }

    func message(_ key: String) -> (text: String, isError: Bool)? {
        if let error = errors[key] { return (error, true) }
        if let note = notes[key] { return (note, false) }
        return nil
    }
}

/// Settings > Engines: Claude Code and Codex as found on this Mac and as the server sees
/// them, install and sign-in steps when missing, and the per-engine defaults.
struct EnginesSettings: View {
    @Environment(AppState.self) private var state
    @State private var model = EnginesModel()

    var body: some View {
        Form {
            if state.officePath == nil {
                Section {
                    Text("Choose an office folder in General first; engine defaults live in its office.toml.")
                        .foregroundStyle(.secondary)
                }
            }
            defaultSection
            ForEach(EngineKind.allCases) { engine in
                engineSection(engine)
            }
            Section {
                Text(
                    "The server looks for claude and codex on its own PATH when it starts an advisor run; "
                        + "the app cannot point it at the copy found here. The Server line is the server's own verdict."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .task(id: state.api?.baseURL) {
            async let detect: Void = model.detect()
            async let server: Void = model.loadServer(api: state.api)
            _ = await (detect, server)
        }
    }

    // MARK: - Default engine

    private var defaultSection: some View {
        Section {
            Picker(
                "Default engine",
                selection: Binding(
                    get: { model.defaultEngine },
                    set: { value in
                        model.defaultEngine = value
                        Task {
                            await model.set(
                                "serve.engines.default", value, office: state.officePath, api: state.api)
                        }
                    })
            ) {
                ForEach(EngineKind.allCases) { engine in
                    Text(engine.label).tag(engine.rawValue)
                }
            }
            .pickerStyle(.segmented)
            .disabled(state.officePath == nil || model.catalog == nil)
            fieldMessage("serve.engines.default")
            if let error = model.serverError {
                Text(error).font(.caption).foregroundStyle(.secondary)
            }
        } header: {
            HStack {
                Text("Engines")
                Spacer()
                if model.detecting {
                    ProgressView().controlSize(.small)
                }
                Button("Check Again") {
                    Task {
                        await model.detect()
                        await model.loadServer(api: state.api)
                    }
                }
                .disabled(model.detecting)
            }
        }
    }

    // MARK: - One engine

    @ViewBuilder
    private func engineSection(_ engine: EngineKind) -> some View {
        let detection = model.detections[engine]
        Section(engine.label) {
            if let detection {
                if let location = detection.location {
                    LabeledContent("Found") {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text((location.path as NSString).abbreviatingWithTildeInPath)
                                .font(.system(.body, design: .monospaced))
                                .textSelection(.enabled)
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Text("via \(location.source.rawValue)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    LabeledContent("Version", value: detection.version ?? "did not answer --version")
                    LabeledContent("Sign-in", value: detection.signIn.label)
                    if detection.signIn == .signedOut {
                        Text("Sign in from Terminal, then Check Again:")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        CommandText(engine.signInCommand)
                    }
                } else {
                    LabeledContent("Found", value: "Not installed")
                    installGuidance(engine)
                }
            } else {
                LabeledContent("Found", value: "Checking…")
            }
            serverLine(engine)
            defaults(engine)
        }
    }

    @ViewBuilder
    private func installGuidance(_ engine: EngineKind) -> some View {
        Text("Install it with one of these commands in Terminal, sign in, then Check Again:")
            .font(.caption)
            .foregroundStyle(.secondary)
        ForEach(engine.installCommands, id: \.self) { command in
            CommandText(command)
        }
        Text(engine.billingNote)
            .font(.caption)
            .foregroundStyle(.secondary)
        Link("Installation guide", destination: engine.installGuide)
            .font(.caption)
    }

    @ViewBuilder
    private func serverLine(_ engine: EngineKind) -> some View {
        if let status = model.runner?.engine(engine.rawValue) {
            LabeledContent("Server") {
                if status.usable {
                    Label("Usable\(status.version.map { " (\($0))" } ?? "")", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Label("Not usable", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
            }
            if !status.usable, let message = status.message {
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
        } else {
            LabeledContent("Server", value: state.api == nil ? "Not running" : "Not reported")
        }
    }

    // MARK: - Defaults

    @ViewBuilder
    private func defaults(_ engine: EngineKind) -> some View {
        let available = state.officePath != nil && model.catalog != nil
        Group {
            Toggle(
                "Enabled",
                isOn: Binding(
                    get: { model.enabled[engine] ?? true },
                    set: { value in
                        model.enabled[engine] = value
                        save(model.key(engine, "enabled"), value ? "true" : "false")
                    }))
            fieldMessage(model.key(engine, "enabled"))

            Picker(
                "Model",
                selection: Binding(
                    get: { model.modelChoice[engine] ?? EnginesModel.otherModel },
                    set: { value in
                        model.modelChoice[engine] = value
                        if value != EnginesModel.otherModel {
                            save(model.key(engine, "model"), value)
                        }
                    })
            ) {
                ForEach(model.models(engine)) { option in
                    Text(option.recommended == true ? "\(option.label) (recommended)" : option.label)
                        .tag(option.id)
                }
                Divider()
                Text("Other…").tag(EnginesModel.otherModel)
            }
            if model.modelChoice[engine] == EnginesModel.otherModel {
                textRow(engine, field: "model", label: "Model name", prompt: "model id", text: $model.otherModel)
            }
            fieldMessage(model.key(engine, "model"))

            Picker(
                "Effort",
                selection: Binding(
                    get: { model.effort[engine] ?? "medium" },
                    set: { value in
                        model.effort[engine] = value
                        save(model.key(engine, "effort"), value)
                    })
            ) {
                ForEach(model.efforts(engine), id: \.self) { effort in
                    Text(effort.capitalized).tag(effort)
                }
            }
            .pickerStyle(.segmented)
            fieldMessage(model.key(engine, "effort"))

            textRow(engine, field: "max_budget_usd", label: "Budget per run (USD)", prompt: "2.0", text: $model.budget)
            fieldMessage(model.key(engine, "max_budget_usd"))
        }
        .disabled(!available)
    }

    private func textRow(
        _ engine: EngineKind, field: String, label: String, prompt: String,
        text: Binding<[EngineKind: String]>
    ) -> some View {
        let key = model.key(engine, field)
        let value = Binding(get: { text.wrappedValue[engine] ?? "" }, set: { text.wrappedValue[engine] = $0 })
        return LabeledContent(label) {
            HStack {
                TextField(label, text: value, prompt: Text(prompt))
                    .labelsHidden()
                    .multilineTextAlignment(.trailing)
                    .frame(width: 160)
                    .onSubmit { save(key, value.wrappedValue) }
                Button("Set") { save(key, value.wrappedValue) }
                    .disabled(!model.isDirty(key, value.wrappedValue) || model.busy.contains(key))
            }
        }
    }

    @ViewBuilder
    private func fieldMessage(_ key: String) -> some View {
        if let message = model.message(key) {
            Text(message.text)
                .font(.caption)
                .foregroundStyle(message.isError ? .red : .secondary)
        }
    }

    private func save(_ key: String, _ value: String) {
        Task {
            await model.set(key, value, office: state.officePath, api: state.api)
        }
    }
}
