import FOKit
import SwiftUI

/// Research: the five key providers from the Connectors pane, all optional.
struct ResearchStep: View {
    let model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            StepHeader(
                title: "Add research keys",
                detail: "Optional. Quotes, economic data, web search and deep research each use a key "
                    + "from the provider. Add any now, or later in Settings > Connectors."
            )
            ConnectorsSettings(model: model.research, parts: [.keys])
                .padding(.horizontal, -20)
        }
    }
}
