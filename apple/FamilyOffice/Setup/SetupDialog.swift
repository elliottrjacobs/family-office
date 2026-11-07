import AppKit
import FOKit
import SwiftUI

/// The first-run setup dialog (plan R7 to R11, flow F1): a 720 by 520 sheet with a progress
/// bar, the current step, and Back, Skip and a primary button whose label follows the step.
/// Return presses the primary button unless a text field or the terminal has focus.
struct SetupDialog: View {
    @Environment(AppState.self) private var state
    let model: SetupModel

    var body: some View {
        VStack(spacing: 0) {
            progress
            Divider()
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(.horizontal, 28)
                .padding(.top, 20)
            Divider()
            footer
        }
        .frame(width: 720, height: 520)
        .background(ReturnKeyMonitor { focus in model.handleReturn(focus: focus, state: state) })
        #if DEBUG
        .task(id: model.flow.index) { await debugWalk() }
        #endif
    }

    private var progress: some View {
        HStack(spacing: 12) {
            ProgressView(value: model.flow.progress)
                .progressViewStyle(.linear)
                .accessibilityLabel("Setup progress")
            Text("Step \(model.flow.index + 1) of \(model.flow.steps.count)")
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private var content: some View {
        switch model.step {
        case .welcome: WelcomeStep(model: model)
        case .office: OfficeStep(model: model)
        case .engine: EngineStep(model: model)
        case .accounts: AccountsStep(model: model)
        case .research: ResearchStep(model: model)
        case .phone: PhoneStep(model: model)
        case .done: DoneStep(model: model)
        }
    }

    private var footer: some View {
        HStack {
            if model.step != .done {
                Button("Finish Later") { state.closeSetup() }
                    .buttonStyle(.link)
                    .help("Close setup. It opens again at the next launch, or from Help > Set Up Family Office…")
            }
            Spacer()
            if model.flow.canGoBack {
                Button("Back") { model.back() }
            }
            if model.flow.canSkip {
                Button(model.skipLabel) { model.skip() }
            }
            Button(model.primaryLabel) { model.primary(state: state) }
                .buttonStyle(.borderedProminent)
                .disabled(!model.primaryEnabled)
        }
        .controlSize(.large)
        .padding(.horizontal, 28)
        .padding(.vertical, 14)
    }

    #if DEBUG
    /// `-debugSetupWalk PARENT` drives the dialog without clicking, for walkthroughs: Get
    /// Started, create `family-office` in PARENT with `fo setup --offline`, Continue once the
    /// server reports the office, skip the optional steps, and finish.
    private func debugWalk() async {
        guard let parent = UserDefaults.standard.string(forKey: "debugSetupWalk"), !parent.isEmpty else { return }
        try? await Task.sleep(for: .seconds(1))
        switch model.step {
        case .welcome:
            model.primary(state: state)
        case .office:
            guard model.setupSession == nil, model.chosenOffice == nil else { return }
            model.setParent(URL(fileURLWithPath: (parent as NSString).expandingTildeInPath))
            model.create(state: state)
            while !Task.isCancelled, !model.officeReady {
                try? await Task.sleep(for: .milliseconds(500))
            }
            guard !Task.isCancelled else { return }
            try? await Task.sleep(for: .seconds(1))
            model.primary(state: state)
        case .engine, .accounts, .research, .phone:
            model.skip()
        case .done:
            model.primary(state: state)
        }
    }
    #endif
}

/// One step's heading: a title and a sentence or two.
struct StepHeader: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.title2.weight(.semibold))
            Text(detail)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.bottom, 12)
    }
}

/// Watches Return in the dialog's window and offers it to the dialog first. Return in a text
/// field (the field editor) or the embedded terminal is left alone, and so is Return in any
/// other window, such as a terminal sheet on top of the dialog.
struct ReturnKeyMonitor: NSViewRepresentable {
    let onReturn: @MainActor (SetupFocus) -> Bool

    func makeNSView(context: Context) -> MonitorView {
        let view = MonitorView()
        view.onReturn = onReturn
        return view
    }

    func updateNSView(_ view: MonitorView, context: Context) {
        view.onReturn = onReturn
    }

    static func dismantleNSView(_ view: MonitorView, coordinator: ()) {
        view.removeMonitor()
    }

    final class MonitorView: NSView {
        var onReturn: (@MainActor (SetupFocus) -> Bool)?
        private var monitor: Any?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            removeMonitor()
            guard window != nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, let window = self.window, event.window === window else { return event }
                // Return (36) and Enter on the keypad (76), with no modifier.
                guard event.keyCode == 36 || event.keyCode == 76,
                    event.modifierFlags.intersection([.command, .option, .control, .shift]).isEmpty
                else { return event }
                let focus = Self.focus(window.firstResponder)
                return MainActor.assumeIsolated { self.onReturn?(focus) ?? false } ? nil : event
            }
        }

        func removeMonitor() {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
            monitor = nil
        }

        static func focus(_ responder: NSResponder?) -> SetupFocus {
            if responder is FoTerminalNSView { return .terminal }
            if let text = responder as? NSTextView, text.isFieldEditor || text.isEditable { return .textField }
            return .other
        }
    }
}
