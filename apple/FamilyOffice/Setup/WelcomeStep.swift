import SwiftUI

/// Welcome: what the app is, in two sentences.
struct WelcomeStep: View {
    let model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Spacer(minLength: 0)
            Text("Welcome to Family Office")
                .font(.largeTitle.weight(.semibold))
            Text(
                "Family Office keeps your household's finances in one folder on this Mac, and its "
                    + "advisors run through Claude Code or Codex on your own account. "
                    + "Nothing here can trade or move money."
            )
            .font(.title3)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: 560, alignment: .leading)
            Text("Setup takes a few minutes. Every step after the office can wait until later.")
                .font(.callout)
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
        }
    }
}
