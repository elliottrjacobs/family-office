import FOKit
import SwiftUI

/// Engine: the Engines pane itself (detection, the server's verdict, default engine, model
/// and effort), with Later allowed.
struct EngineStep: View {
    let model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            StepHeader(
                title: model.profile == .new ? "Choose how advisors run" : "Check how advisors run",
                detail: model.profile == .new
                    ? "Advisors run through Claude Code or Codex, signed in to your own account, which "
                        + "bills you directly. Pick a default engine, model and effort; you can change "
                        + "them any time in Settings > Engines."
                    : "Your office is set up. Confirm the engine, model and effort advisors use; runs "
                        + "bill through your own Claude or ChatGPT account."
            )
            EnginesSettings(model: model.engines)
                .padding(.horizontal, -20)
        }
    }
}
