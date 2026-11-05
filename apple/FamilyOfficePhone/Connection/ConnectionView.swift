import FOKit
import SwiftUI

/// The paired Mac: whether it answers, when it last did, and what to do when it does not.
struct ConnectionView: View {
    @Bindable var model: PhoneModel
    @State private var confirmingUnpair = false

    static let requirement = "Your Mac must be awake and on your tailnet, with Family Office open."

    private var url: URL? { model.session.url }

    private var problem: String? {
        if case .offline(let message) = model.phase { return message }
        return nil
    }

    var body: some View {
        List {
            Section {
                VStack(spacing: 8) {
                    Image(systemName: "desktopcomputer")
                        .font(.system(size: 44))
                        .foregroundStyle(.tint)
                        .accessibilityHidden(true)
                    Text(url.map(PhoneModel.macName(for:)) ?? "Your Mac")
                        .font(.title2.bold())
                    if let host = url?.host {
                        Text(host)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .listRowBackground(Color.clear)
            }

            Section {
                LabeledContent("Status") {
                    HStack(spacing: 6) {
                        Circle().fill(statusColor).frame(width: 8, height: 8)
                        Text(statusText)
                    }
                }
                LabeledContent("Last seen") {
                    if let seen = model.lastSeen {
                        Text(seen, format: .relative(presentation: .named))
                    } else {
                        Text("Never")
                    }
                }
                if let version = model.session.serverVersion {
                    LabeledContent("Family Office on the Mac", value: version)
                }
            } footer: {
                Text(Self.requirement)
            }

            if let problem {
                Section {
                    Notice(text: problem)
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                }
            }

            if model.session.updateAdvised, let version = model.session.serverVersion {
                Section {
                    Label {
                        Text(
                            "The Mac runs Family Office \(version), newer than this app was built for "
                                + "(\(DeviceSession.knownServerVersions.lowerBound.major)."
                                + "\(DeviceSession.knownServerVersions.lowerBound.minor)). "
                                + "Update the iPhone app if something looks wrong.")
                    } icon: {
                        Image(systemName: "arrow.down.app")
                    }
                    .font(.callout)
                }
            }

            Section {
                Button {
                    model.retry()
                } label: {
                    HStack {
                        Text(model.phase == .connected ? "Reconnect" : "Retry")
                        Spacer()
                        if model.phase == .connecting {
                            ProgressView()
                        }
                    }
                }
                .disabled(model.phase == .connecting)
            }

            Section {
                Button("Unpair This iPhone", role: .destructive) {
                    confirmingUnpair = true
                }
                .confirmationDialog(
                    "Unpair this iPhone?", isPresented: $confirmingUnpair, titleVisibility: .visible
                ) {
                    Button("Unpair", role: .destructive) { model.unpair() }
                } message: {
                    Text("You will need a new code from the Mac to pair again.")
                }
            } footer: {
                Text("Unpairing forgets the pairing on this iPhone only. Revoke it on the Mac in Settings > Devices to remove it there.")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Connection")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await model.connect() }
    }

    private var statusText: String {
        switch model.phase {
        case .connecting: return "Connecting…"
        case .connected: return model.reachable ? "Reachable" : "Checking…"
        case .idle, .offline: return model.reachable ? "Reachable" : "Not reachable"
        }
    }

    private var statusColor: Color {
        switch model.phase {
        case .connecting: return .gray
        case .connected: return model.reachable ? .green : .gray
        case .idle, .offline: return model.reachable ? .green : .orange
        }
    }
}
