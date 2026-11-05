import FOKit
import SwiftUI

/// Done: what is set up, what was skipped, and where to finish each later.
struct DoneStep: View {
    let model: SetupModel

    var body: some View {
        let summary = model.flow.summary
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(
                title: model.profile == .new ? "Your office is ready" : "You're all set",
                detail: summary.skipped.isEmpty
                    ? "Everything is set up. Home lists what to try first."
                    : "Home keeps a getting-started checklist for what is still open."
            )
            if !summary.completed.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Set up").font(.headline)
                    ForEach(summary.completed, id: \.self) { line in
                        Label(line, systemImage: "checkmark.circle.fill")
                            .symbolRenderingMode(.multicolor)
                    }
                }
            }
            if !summary.skipped.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Skipped for now").font(.headline)
                    ForEach(summary.skipped) { step in
                        Label(Self.later(step), systemImage: "circle.dashed")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Spacer(minLength: 0)
            Text("Run setup again any time from Help > Set Up Family Office….")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    static func later(_ step: SetupStep) -> String {
        switch step {
        case .engine: return "Engine: choose one in Settings > Engines"
        case .accounts: return "Accounts: connect in Settings > Connectors"
        case .research: return "Research keys: add in Settings > Connectors"
        case .phone: return "Phone: pair in Settings > Devices"
        case .welcome, .office, .done: return step.rawValue.capitalized
        }
    }
}
