import FOKit
import SwiftUI
import UIKit

/// The first screen: what to do on the Mac, then scan its code (or type it on a simulator or
/// a phone without a camera).
struct PairingView: View {
    @Bindable var model: PhoneModel

    @State private var name = UIDevice.current.name
    @State private var scanning = false
    @State private var manual = false
    @State private var manualURL = ""
    @State private var manualCode = ""
    @State private var problem: String?
    @State private var busy = false
    @FocusState private var focus: Field?

    private enum Field { case url, code }

    private var reason: String? {
        if case .unpaired(let reason) = model.session.state { return reason }
        return nil
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    header
                    if let message = problem ?? reason {
                        Notice(text: message)
                    }
                    steps
                    nameField
                    actions
                    if manual {
                        manualEntry
                    }
                    Text("Your iPhone must be on the same tailnet as the Mac, with Tailscale on.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding(20)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color(.systemGroupedBackground))
            .navigationBarTitleDisplayMode(.inline)
            .disabled(busy)
            .overlay {
                if busy {
                    ProgressView("Pairing…")
                        .padding(24)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                }
            }
            .sheet(isPresented: $scanning) {
                QRScannerView { text in
                    scanning = false
                    switch PairingInput.payload(fromScanned: text) {
                    case .success(let payload): pair(payload)
                    case .failure(let failure): problem = failure.message
                    }
                } onManualEntry: {
                    scanning = false
                    manual = true
                    focus = .url
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: "laptopcomputer.and.iphone")
                .font(.system(size: 40))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            Text("Pair with your Mac")
                .font(.largeTitle.bold())
            Text("This iPhone shows the office your Mac keeps. Pair once; the Mac can revoke this iPhone at any time.")
                .foregroundStyle(.secondary)
        }
    }

    private var steps: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                Step(number: 1, text: "Open Family Office on your Mac.")
                Step(number: 2, text: "Go to Settings > Devices.")
                Step(number: 3, text: "Click Pair a Phone, then scan the code it shows.")
            }
        }
    }

    private var nameField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("This iPhone's name")
                .font(.footnote.weight(.medium))
                .foregroundStyle(.secondary)
            TextField("iPhone", text: $name)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled()
                .padding(12)
                .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
            Text("The Mac lists this name in Settings > Devices.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private var actions: some View {
        VStack(spacing: 12) {
            Button {
                problem = nil
                scanning = true
            } label: {
                Label("Scan Code", systemImage: "qrcode.viewfinder")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(trimmedName.isEmpty)

            Button(manual ? "Hide Manual Entry" : "Enter Code Manually") {
                withAnimation { manual.toggle() }
                focus = manual ? .url : nil
            }
            .font(.callout)
        }
    }

    private var manualEntry: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                Text("Type the address and code the Mac shows under Pair a Phone.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                TextField("example-mac.tail0000.ts.net", text: $manualURL)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.next)
                    .focused($focus, equals: .url)
                    .onSubmit { focus = .code }
                    .accessibilityLabel("Mac address")
                Divider()
                TextField("ABCD-2345", text: $manualCode)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())
                    .submitLabel(.go)
                    .focused($focus, equals: .code)
                    .onSubmit(pairManually)
                    .accessibilityLabel("Pairing code")
                Button(action: pairManually) {
                    Text("Pair").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(manualURL.isEmpty || manualCode.isEmpty || trimmedName.isEmpty)
            }
        }
    }

    private func pairManually() {
        focus = nil
        guard !trimmedName.isEmpty else { return }
        switch PairingInput.payload(url: manualURL, code: manualCode) {
        case .success(let payload): pair(payload)
        case .failure(let failure): problem = failure.message
        }
    }

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func pair(_ payload: PairingPayload) {
        problem = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                try await model.pair(payload: payload, name: trimmedName)
                manualCode = ""
            } catch let error as DeviceSessionError {
                problem = error.message
            } catch {
                problem = "Pairing failed."
            }
        }
    }
}

private struct Step: View {
    let number: Int
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text("\(number)")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(Circle().fill(.tint))
            Text(text)
        }
    }
}

/// A white rounded card on the grouped background, as in the app's other phone screens.
struct Card<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

/// A short explanation of why the phone is here: a revoke, a refused code, a missing identity.
struct Notice: View {
    let text: String

    var body: some View {
        Label {
            Text(text)
        } icon: {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(.orange)
        }
        .font(.callout)
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
    }
}
