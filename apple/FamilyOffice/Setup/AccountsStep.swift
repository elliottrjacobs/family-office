import FOKit
import SwiftUI

/// Accounts: the Connectors pane's Schwab and SimpleFIN rows (`fo auth` in the terminal),
/// a note on CSV imports, and, once a provider is connected, the first `fo sync`.
struct AccountsStep: View {
    @Environment(AppState.self) private var state
    @Bindable var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            StepHeader(
                title: model.profile == .new ? "Connect your accounts" : "Check your accounts",
                detail: "Family Office reads balances, positions and transactions; it never trades or "
                    + "moves money. Connecting runs fo auth in a terminal here, and your credentials "
                    + "stay in the office's secrets folder."
            )
            ConnectorsSettings(model: model.accounts, parts: [.accounts])
                .padding(.horizontal, -20)
                .frame(maxHeight: 250)
            HStack(alignment: .firstTextBaseline) {
                if model.anyAccountConnected {
                    Button(model.firstSyncFinished ? "Sync Again" : "Run First Sync") {
                        model.runFirstSync(office: state.officePath)
                    }
                    Text(
                        model.firstSyncFinished
                            ? "First sync finished."
                            : "Pulls balances, positions and transactions with fo sync."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                } else {
                    Text(
                        "Prefer CSV exports? Skip this step and import them later: place them in the "
                            + "office's imports folder and run the onboard skill from your coding agent."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.top, 8)
        }
        .sheet(item: $model.syncSession) { session in
            TerminalSheet(session: session) { model.syncSession = nil }
        }
    }
}
