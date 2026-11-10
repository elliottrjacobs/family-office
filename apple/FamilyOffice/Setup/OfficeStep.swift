import FOKit
import SwiftUI

/// Office: create a new office with `fo setup PATH --offline` in the embedded terminal, or
/// open a folder that holds `office.toml`. Either way the app stores the folder and restarts
/// the server on it, and the step completes when the server's onboarding state reports the
/// office.
struct OfficeStep: View {
    @Environment(AppState.self) private var state
    @Bindable var model: SetupModel
    @State private var stopper = TerminalStopper()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            StepHeader(
                title: "Where should your office live?",
                detail: "Your office is one folder on this Mac: profile, accounts, reports and notes. "
                    + "Create a new one, or open one you already have."
            )
            if let session = model.setupSession {
                terminal(session)
            } else if model.chosenOffice == nil {
                Picker("", selection: $model.officeMode) {
                    Text("Create a new office").tag(SetupModel.OfficeMode.create)
                    Text("Open an existing office").tag(SetupModel.OfficeMode.open)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 380)
                if model.officeMode == .create { createForm } else { openForm }
            }
            if model.chosenOffice != nil {
                readiness
            }
            if let error = model.officeError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .task(id: "\(state.api?.baseURL.absoluteString ?? "")|\(model.chosenOffice ?? "")") {
            // The server restarts on the new folder; ask it until it reports the office.
            while !Task.isCancelled, model.chosenOffice != nil, !model.officeReady {
                await model.checkOffice(api: state.api, officePath: state.officePath)
                if model.officeReady { break }
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private var createForm: some View {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
            GridRow {
                Text("Location")
                HStack {
                    Text(model.parentFolder.map { ($0.path as NSString).abbreviatingWithTildeInPath } ?? "Not chosen")
                        .foregroundStyle(model.parentFolder == nil ? .secondary : .primary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Button("Choose…") { model.chooseParent() }
                }
            }
            GridRow {
                Text("Folder name")
                TextField("Folder name", text: $model.officeName, prompt: Text("family-office"))
                    .labelsHidden()
                    .frame(width: 240)
            }
            GridRow {
                Color.clear.frame(width: 1, height: 1)
                VStack(alignment: .leading, spacing: 8) {
                    if let path = model.newOfficePath {
                        Text("Creates \((path as NSString).abbreviatingWithTildeInPath) with fo setup --offline.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Button("Create Office") { model.create(state: state) }
                        .disabled(model.newOfficePath == nil)
                }
            }
        }
        .padding(.top, 8)
    }

    private var openForm: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Choose the folder that contains office.toml. It may live anywhere on this Mac.")
                .foregroundStyle(.secondary)
            Button("Choose Office Folder…") { model.openExisting(state: state) }
        }
        .padding(.top, 8)
    }

    @ViewBuilder
    private func terminal(_ session: FoTerminalSession) -> some View {
        FoTerminalView(session: session, stopper: stopper)
            .frame(minHeight: 200)
            .clipShape(RoundedRectangle(cornerRadius: 8))
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
            Spacer()
            if case .exited(let status) = session.phase, status != 0 {
                Button("Try Again") { model.create(state: state) }
            }
        }
    }

    @ViewBuilder
    private var readiness: some View {
        HStack(spacing: 6) {
            if model.officeReady {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text("The server opened \((model.chosenOffice.map { ($0 as NSString).abbreviatingWithTildeInPath }) ?? "the office"). Continue when you are ready.")
            } else {
                ProgressView().controlSize(.small)
                Text("Starting the server on the office…")
            }
        }
        .font(.callout)
    }
}
