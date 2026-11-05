import FOKit
import SwiftUI

@main
struct FamilyOfficePhoneApp: App {
    @State private var model = PhoneModel(session: DeviceSession(store: Keychain()))

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
        }
    }
}

/// Unpaired goes to pairing; paired and reachable shows the office in a web view under a
/// small status bar; paired and unreachable shows the connection screen.
struct RootView: View {
    @Bindable var model: PhoneModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            switch model.session.state {
            case .unpaired, .pairing:
                PairingView(model: model)
            case .paired:
                if model.phase == .connected, let url = model.session.url {
                    OfficeScreen(model: model, url: url)
                } else {
                    NavigationStack {
                        ConnectionView(model: model)
                    }
                }
            }
        }
        .animation(.default, value: model.phase)
        .onChange(of: scenePhase, initial: true) { _, phase in
            switch phase {
            case .active: model.resume()
            case .background: model.suspend()
            default: break
            }
        }
    }
}

/// The office web view with a one-line status bar above it.
struct OfficeScreen: View {
    @Bindable var model: PhoneModel
    let url: URL
    @State private var showingConnection = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Circle()
                    .fill(model.reachable ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                    .accessibilityHidden(true)
                Text(PhoneModel.macName(for: url))
                    .font(.footnote.weight(.medium))
                    .lineLimit(1)
                Text(model.reachable ? "Connected" : "Checking…")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    model.reload()
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .accessibilityLabel("Reload")
                Button {
                    showingConnection = true
                } label: {
                    Image(systemName: "info.circle")
                }
                .accessibilityLabel("Connection")
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(.bar)
            Divider()
            OfficeWebView(
                url: url, cookies: model.session.cookies, reloadToken: model.reloadToken
            ) { reason in
                model.revoked(reason: reason)
            }
            .ignoresSafeArea(edges: .bottom)
        }
        .sheet(isPresented: $showingConnection) {
            NavigationStack {
                ConnectionView(model: model)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { showingConnection = false }
                        }
                    }
            }
        }
    }
}
