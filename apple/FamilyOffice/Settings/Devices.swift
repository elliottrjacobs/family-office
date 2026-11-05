import AppKit
import FOKit
import Observation
import SwiftUI

/// State behind Settings > Devices: Tailscale, the office's tailnet name, `tailscale serve`,
/// the pairing code on screen, and revocation.
@MainActor
@Observable
final class DevicesModel {
    /// Nil while checking.
    private(set) var tailscale: TailscaleState?
    /// `[serve] tailnet_name` from office.toml, through `fo config get`.
    private(set) var tailnetName: String?
    private(set) var configuredPort: Int?
    private(set) var configError: String?
    private(set) var nameNote: String?

    private(set) var serveBusy = false
    private(set) var serveOutput: String?
    private(set) var serveFailed = false

    /// The code on screen. It lives only here and in the QR image, never in a log.
    private(set) var pairing: PairingCode?
    private(set) var qrImage: CGImage?
    private(set) var pairingError: String?
    private(set) var pairingBusy = false
    private(set) var pairedCountAtCode = 0
    private(set) var pairedNote: String?

    private(set) var revokeError: String?

    static let defaultPort = 4790

    func refresh(office: String?) async {
        tailscale = await Tailscale.detect()
        configError = nil
        guard office != nil else {
            tailnetName = nil
            configuredPort = nil
            return
        }
        switch await FoCommand.configGet(office: office, "serve.tailnet_name") {
        case .success(let value): tailnetName = value.map(\.fieldText).flatMap { $0.isEmpty ? nil : $0 }
        case .failure(let error): configError = error.message
        }
        if case .success(let value) = await FoCommand.configGet(office: office, "serve.port") {
            configuredPort = value.flatMap { Int($0.fieldText) }
        }
        let kind: String =
            switch tailscale {
            case .notInstalled, nil: "not-installed"
            case .stopped: "stopped"
            case .running(_, let name): name == nil ? "running-no-dns" : "running"
            }
        settingsLog.info(
            "devices: tailscale=\(kind, privacy: .public) tailnetNameSet=\(self.tailnetName != nil, privacy: .public) port=\(self.configuredPort ?? 0, privacy: .public)"
        )
    }

    /// `fo config set serve.tailnet_name NAME`.
    func useName(_ name: String, office: String?) async {
        nameNote = nil
        switch await FoCommand.configSet(office: office, "serve.tailnet_name", name) {
        case .success(let value):
            tailnetName = value.fieldText
            configError = nil
            nameNote = "Saved. Restart the server (or turn on phone access in General) to use it."
        case .failure(let error):
            configError = error.message
        }
    }

    /// `tailscale serve --bg PORT` after the user confirmed.
    func startServe(port: Int) async {
        await serve(Tailscale.serveArguments(port: port))
    }

    func stopServe() async {
        await serve(Tailscale.stopArguments)
    }

    private func serve(_ arguments: [String]) async {
        guard let cli = tailscale?.cli else { return }
        serveBusy = true
        defer { serveBusy = false }
        let result = await Tailscale.run(cli, arguments, timeout: 10)
        let text = [result.stdoutText, result.stderrText]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        if result.timedOut {
            serveFailed = true
            serveOutput = "tailscale did not finish within 10 seconds." + (text.isEmpty ? "" : "\n" + text)
        } else if !result.launched {
            serveFailed = true
            serveOutput = "tailscale could not be started."
        } else {
            serveFailed = result.status != 0
            serveOutput = text.isEmpty ? (serveFailed ? "tailscale exited with status \(result.status)." : "Done.") : text
        }
    }

    func requestCode(api: APIClient?, tailnetName: String, pairedCount: Int) async {
        guard let api else {
            pairingError = "The server is not running."
            return
        }
        pairingBusy = true
        defer { pairingBusy = false }
        pairingError = nil
        pairedNote = nil
        do {
            let code = try await api.requestPairingCode()
            pairing = code
            qrImage = QRCode.image(for: PairingPayload(tailnetName: tailnetName, code: code.code).encoded())
            pairedCountAtCode = pairedCount
        } catch {
            pairingError = Pairing.explain(error)
        }
    }

    func clearCode() {
        pairing = nil
        qrImage = nil
    }

    /// Hides the code once a new device shows up in the list.
    func devicesChanged(_ devices: [Device]) {
        guard pairing != nil, devices.count > pairedCountAtCode else { return }
        clearCode()
        pairedNote = devices.last.map { "Paired \($0.name)." } ?? "Paired."
    }

    func revoke(_ device: Device, api: APIClient?) async -> Bool {
        revokeError = nil
        guard let api else {
            revokeError = "The server is not running."
            return false
        }
        do {
            try await api.revokeDevice(id: device.id)
            return true
        } catch {
            revokeError = Pairing.explain(error)
            return false
        }
    }
}

/// Settings > Devices: Tailscale status, the tailnet name, `tailscale serve`, pairing by QR
/// code, and the paired phones with Revoke.
struct DevicesSettings: View {
    @Environment(AppState.self) private var state
    @State private var model = DevicesModel()
    @State private var confirmServe = false
    @State private var revoking: Device?

    /// The port `tailscale serve` forwards to: the live server's when it runs with `--remote`,
    /// else the configured one.
    private var servePort: Int {
        if state.phoneAccess, let port = state.handshake?.port { return port }
        return model.configuredPort ?? DevicesModel.defaultPort
    }

    var body: some View {
        Form {
            tailscaleSection
            accessSection
            pairingSection
            devicesSection
        }
        .formStyle(.grouped)
        .task(id: state.officePath) {
            await model.refresh(office: state.officePath)
            await state.refreshMonitor()
        }
        .task(id: model.pairing?.expiresAt) {
            // While a code is on screen, look for the new phone every few seconds.
            guard model.pairing != nil else { return }
            while !Task.isCancelled, model.pairing != nil {
                try? await Task.sleep(for: .seconds(3))
                await state.refreshMonitor()
                model.devicesChanged(state.monitor.devices ?? [])
            }
        }
        .sheet(isPresented: $confirmServe) {
            ServeConfirmation(port: servePort, name: model.tailnetName) {
                confirmServe = false
                Task { await model.startServe(port: servePort) }
            } cancel: {
                confirmServe = false
            }
        }
        .confirmationDialog(
            "Revoke \(revoking?.name ?? "this device")?",
            isPresented: Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } }),
            presenting: revoking
        ) { device in
            Button("Revoke", role: .destructive) {
                Task {
                    if await model.revoke(device, api: state.api) {
                        await state.refreshMonitor()
                    }
                }
            }
        } message: { _ in
            Text("The phone's next request fails and it returns to its pairing screen. Pair it again to restore access.")
        }
    }

    // MARK: - Tailscale

    @ViewBuilder
    private var tailscaleSection: some View {
        Section("Tailscale") {
            switch model.tailscale {
            case nil:
                HStack {
                    ProgressView().controlSize(.small)
                    Text("Checking Tailscale…")
                }
            case .notInstalled:
                Text(
                    "Tailscale is not installed. Your phone reaches this Mac only over your own tailnet, which Tailscale provides; nothing is opened to the internet."
                )
                Link("Download Tailscale for Mac", destination: Tailscale.downloadURL)
                Text("After installing it and signing in, share the server on your tailnet with:")
                    .font(.caption)
                CommandText(Tailscale.serveCommand(port: servePort))
                Text("Turn on MagicDNS and HTTPS certificates for your tailnet in the Tailscale admin console first.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case .stopped(_, let detail):
                Text(detail)
                Text("Open Tailscale and connect, then check again.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Open Tailscale") { openTailscale() }
                    Button("Check Again") { Task { await model.refresh(office: state.officePath) } }
                }
            case .running(_, let dnsName):
                LabeledContent("This Mac") {
                    Text(dnsName ?? "No MagicDNS name (turn on MagicDNS)")
                        .textSelection(.enabled)
                }
                LabeledContent("Office tailnet name") {
                    HStack {
                        Text(model.tailnetName ?? "Not set")
                            .foregroundStyle(model.tailnetName == nil ? .secondary : .primary)
                        if let dnsName, dnsName != model.tailnetName {
                            Button("Use this name") {
                                Task { await model.useName(dnsName, office: state.officePath) }
                            }
                            .disabled(state.officePath == nil)
                        }
                    }
                }
            }
            if let error = model.configError {
                Text(error).font(.caption).foregroundStyle(.red)
            } else if let note = model.nameNote {
                Text(note).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - tailscale serve

    @ViewBuilder
    private var accessSection: some View {
        Section("Tailnet access") {
            Text(
                state.phoneAccess
                    ? "The server runs with --remote on port \(servePort), so tailscale serve can forward the tailnet name to it."
                    : "The server must run with --remote for the tailnet. Turn on Allow phone access over Tailscale in General."
            )
            .font(.caption)
            .foregroundStyle(state.phoneAccess ? Color.secondary : Color.orange)
            HStack {
                Button("Start Tailnet Access…") { confirmServe = true }
                    .disabled(!isRunning || model.serveBusy)
                Button("Stop") { Task { await model.stopServe() } }
                    .disabled(!isRunning || model.serveBusy)
                if model.serveBusy {
                    ProgressView().controlSize(.small)
                }
            }
            if let output = model.serveOutput {
                Text(output)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(model.serveFailed ? .red : .primary)
                    .textSelection(.enabled)
            }
        }
    }

    private var isRunning: Bool {
        if case .running = model.tailscale { return true }
        return false
    }

    // MARK: - Pairing

    @ViewBuilder
    private var pairingSection: some View {
        Section("Pair a phone") {
            if let pairing = model.pairing, let image = model.qrImage {
                PairingCodeView(pairing: pairing, image: image) {
                    model.clearCode()
                }
            } else {
                Text("Scan the code with the Family Office app on your phone. It is valid for five minutes and works once.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Pair a Phone") {
                        guard let name = model.tailnetName else { return }
                        Task {
                            await model.requestCode(
                                api: state.api, tailnetName: name,
                                pairedCount: state.monitor.devices?.count ?? 0)
                        }
                    }
                    .disabled(model.tailnetName == nil || state.api == nil || model.pairingBusy)
                    if model.tailnetName == nil {
                        Text("Set the office tailnet name first.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else if !state.phoneAccess {
                        Text("Turn on phone access in General so the phone can reach the server.")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
            if let error = model.pairingError {
                Text(error).font(.caption).foregroundStyle(.red)
            } else if let note = model.pairedNote {
                Text(note).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Devices

    @ViewBuilder
    private var devicesSection: some View {
        Section("Paired devices") {
            let devices = state.monitor.devices ?? []
            if state.monitor.devices == nil {
                Text(state.api == nil ? "The server is not running." : "Loading…")
                    .foregroundStyle(.secondary)
            } else if devices.isEmpty {
                Text("No phones are paired.")
                    .foregroundStyle(.secondary)
            }
            ForEach(devices) { device in
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(device.name)
                        Text(Self.detail(device))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Revoke…") { revoking = device }
                }
            }
            if let error = model.revokeError {
                Text(error).font(.caption).foregroundStyle(.red)
            }
        }
    }

    static func detail(_ device: Device, now: Date = Date()) -> String {
        let paired = device.createdDate.map { "Paired \($0.formatted(date: .abbreviated, time: .shortened))" } ?? "Paired"
        let seen =
            device.lastSeenDate.map { "last seen \(OfficeSummary.relative(from: $0, to: now))" } ?? "never seen"
        return "\(paired) · \(seen)"
    }

    private func openTailscale() {
        let app = URL(fileURLWithPath: "/Applications/Tailscale.app")
        if FileManager.default.fileExists(atPath: app.path) {
            NSWorkspace.shared.openApplication(at: app, configuration: NSWorkspace.OpenConfiguration())
        } else {
            NSWorkspace.shared.open(Tailscale.downloadURL)
        }
    }
}

/// The QR code, the code in text, and the countdown to its expiry.
private struct PairingCodeView: View {
    let pairing: PairingCode
    let image: CGImage
    let done: () -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let remaining = pairing.expiresDate.map { Pairing.secondsRemaining(until: $0, now: context.date) } ?? 0
            HStack(alignment: .top, spacing: 16) {
                Image(decorative: image, scale: 2)
                    .interpolation(.none)
                    .resizable()
                    .frame(width: 180, height: 180)
                    .opacity(remaining > 0 ? 1 : 0.2)
                    .accessibilityLabel("Pairing QR code")
                VStack(alignment: .leading, spacing: 8) {
                    Text("Code")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(Pairing.grouped(pairing.code))
                        .font(.system(.title2, design: .monospaced).weight(.semibold))
                        .textSelection(.enabled)
                    if remaining > 0 {
                        Text("Expires in \(Pairing.countdown(remaining))")
                            .monospacedDigit()
                            .foregroundStyle(.secondary)
                    } else {
                        Text("Expired. Pair a phone again for a new code.")
                            .foregroundStyle(.orange)
                    }
                    Button(remaining > 0 ? "Done" : "Close", action: done)
                }
            }
        }
    }
}

/// Confirms `tailscale serve` with what it does.
private struct ServeConfirmation: View {
    let port: Int
    let name: String?
    let confirm: () -> Void
    let cancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Start tailnet access?")
                .font(.title3.weight(.semibold))
            Text("Family Office will run:")
            CommandText(Tailscale.serveCommand(port: port))
            Text(
                "Tailscale then serves https://\(name ?? "this Mac's MagicDNS name") to devices signed in to your tailnet and forwards it to the server at 127.0.0.1:\(port). Nothing is published to the internet. A phone still needs a pairing code from this Mac before it can read anything."
            )
            .fixedSize(horizontal: false, vertical: true)
            Text("It stays on, even after Family Office quits, until you press Stop.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel, action: cancel)
                    .keyboardShortcut(.cancelAction)
                Button("Start", action: confirm)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 440)
    }
}

/// A command shown in monospace, selectable, with a Copy button.
struct CommandText: View {
    let command: String

    init(_ command: String) {
        self.command = command
    }

    var body: some View {
        HStack {
            Text(command)
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
            Spacer()
            Button("Copy") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
            }
        }
        .padding(6)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
    }
}
