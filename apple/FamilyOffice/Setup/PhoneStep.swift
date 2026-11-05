import SwiftUI

/// Phone: the Devices pane's Tailscale status and pairing flow, optional.
struct PhoneStep: View {
    let model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            StepHeader(
                title: "Pair a phone",
                detail: "Optional. Your phone reaches this Mac over your own Tailscale network. "
                    + "Pair now, or later in Settings > Devices."
            )
            DevicesSettings()
                .padding(.horizontal, -20)
        }
    }
}
