import FOKit
import LocalAuthentication
import SwiftUI
import UIKit

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
@MainActor
struct RootView: View {
    @Bindable var model: PhoneModel
    @Environment(\.scenePhase) private var scenePhase

    @State private var locked = true
    @State private var needsAuthentication = true
    @State private var authenticationContext: LAContext?

    private var covered: Bool { locked || scenePhase != .active }

    var body: some View {
        Group {
            switch model.session.state {
            case .credentialUnavailable:
                ContentUnavailableView {
                    Label("Pairing Unavailable", systemImage: "lock")
                } description: {
                    Text(DeviceSession.credentialUnavailableExplanation)
                } actions: {
                    Button("Retry") { model.resume() }
                    // An item this build cannot decode stays unreadable; let the owner start over.
                    Button("Unpair This iPhone", role: .destructive) { model.unpair() }
                }
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
        .accessibilityHidden(covered)
        .disabled(covered)
        .allowsHitTesting(!covered)
        // An overlay, not a swap, so the web view keeps its page under the cover.
        .overlay {
            if covered {
                ZStack {
                    Color(uiColor: .systemBackground).ignoresSafeArea()
                    VStack(spacing: 16) {
                        Text("Family Office")
                            .font(.title)
                        if locked && scenePhase == .active {
                            Text("Locked")
                            Button("Unlock") {
                                Task { await unlock() }
                            }
                            .disabled(authenticationContext != nil)
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Family Office privacy cover")
            }
        }
        .onChange(of: scenePhase, initial: true) { _, phase in
            switch phase {
            case .active:
                if !locked {
                    model.resume()
                } else if needsAuthentication {
                    needsAuthentication = false
                    Task { await unlock() }
                }
            case .inactive:
                endEditing()
                model.suspend()
            case .background:
                locked = true
                endEditing()
                needsAuthentication = true
                authenticationContext?.invalidate()
                authenticationContext = nil
                model.suspend()
            default: break
            }
        }
    }

    private func endEditing() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

    private func didUnlock() {
        locked = false
        // LocalAuthentication can finish while its system UI still makes the scene inactive.
        // In that case the next active transition resumes the model.
        if scenePhase == .active { model.resume() }
    }

    private func unlock() async {
        guard locked, scenePhase == .active, authenticationContext == nil else { return }
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            if error?.domain == LAError.errorDomain,
               error?.code == LAError.passcodeNotSet.rawValue {
                didUnlock()
            }
            return
        }
        authenticationContext = context
        let authenticated = (try? await context.evaluatePolicy(
            .deviceOwnerAuthentication,
            localizedReason: "Unlock Family Office to view your office."
        )) == true
        guard authenticationContext === context else { return }
        authenticationContext = nil
        if authenticated { didUnlock() }
    }
}

/// The office web view with a one-line status bar above it.
struct OfficeScreen: View {
    @Bindable var model: PhoneModel
    let url: URL
    @Environment(\.scenePhase) private var scenePhase
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
            ) { _ in
                model.sessionExpired()
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
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { showingConnection = false }
        }
    }
}
