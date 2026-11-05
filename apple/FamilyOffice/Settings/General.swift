import SwiftUI

/// Settings > General: office folder, launch at login, keep awake, and the command line tool.
struct GeneralSettings: View {
    @Environment(AppState.self) private var state

    var body: some View {
        Form {
            officeSection
            startupSection
            powerSection
            commandLineSection
        }
        .formStyle(.grouped)
        .onAppear {
            state.loginItem.refresh()
            state.commandLineTool.verify()
        }
    }

    private var officeSection: some View {
        Section("Office") {
            LabeledContent("Office folder") {
                HStack {
                    Text(state.officeTitle)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                    Button("Change…") {
                        state.chooseOffice()
                    }
                }
            }
            Text("Changing the folder restarts the server with the new office.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var startupSection: some View {
        let login = state.loginItem
        return Section("Startup") {
            Toggle(
                "Launch at login",
                isOn: Binding(get: { login.isOn }, set: { login.setEnabled($0) }))
            Text(login.statusText)
                .font(.caption)
                .foregroundStyle(login.needsApproval || login.failure != nil ? .orange : .secondary)
            if login.needsApproval {
                Button("Open Login Items Settings…") {
                    login.openSystemSettings()
                }
            }
        }
    }

    private var powerSection: some View {
        let power = state.power
        return Section("Power") {
            Toggle(
                "Keep Mac awake while a phone is paired",
                isOn: Binding(get: { power.keepAwake }, set: { power.setKeepAwake($0) })
            )
            .disabled(!power.available && !power.keepAwake)
            Text(
                power.available
                    ? power.stateText
                    : "Available once a phone is paired in Devices. " + power.stateText
            )
            .font(.caption)
            .foregroundStyle(power.failure == nil ? Color.secondary : Color.orange)
        }
    }

    private var commandLineSection: some View {
        let tool = state.commandLineTool
        return Section("Command line tool") {
            LabeledContent("fo") {
                HStack {
                    Text(tool.stateText)
                        .foregroundStyle(.secondary)
                    switch tool.state {
                    case .installed:
                        Button("Remove") { tool.remove() }
                    case .notInstalled, .other:
                        Button("Install") { tool.install() }
                    case .unavailable:
                        EmptyView()
                    }
                }
            }
            if let message = tool.message {
                Text(message)
                    .font(.caption)
            }
            if let command = tool.manualCommand {
                Text(command)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                HStack {
                    Button("Copy Command") { tool.copyManualCommand() }
                    Button("Open Terminal") { tool.openTerminal() }
                    Button("Check Again") { tool.verify() }
                }
            }
            Text("Links \(CommandLineTool.linkPath) to the fo inside this app, so Terminal runs the same version.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
