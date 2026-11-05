import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        @Bindable var state = state
        ZStack(alignment: .top) {
            if let handshake = state.handshake {
                WebView(
                    handshake: handshake,
                    generation: state.pageGeneration,
                    dataStore: state.websiteDataStore,
                    onLoad: { cookies in state.pageLoaded(cookies: cookies) }
                )
            } else {
                Color(nsColor: .windowBackgroundColor)
            }
            if let banner = state.banner {
                BannerView(message: banner, isError: state.bannerIsError)
                    .padding(.top, 12)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: state.banner)
        .sheet(isPresented: $state.showOfficeSheet) {
            OfficeSheet()
        }
    }
}

private struct BannerView: View {
    let message: String
    let isError: Bool

    var body: some View {
        HStack(spacing: 8) {
            if isError {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.yellow)
            } else {
                ProgressView()
                    .controlSize(.small)
            }
            Text(message)
                .font(.callout)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: 560)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(.separator))
        .shadow(radius: 4, y: 2)
        .accessibilityElement(children: .combine)
    }
}

/// First-launch placeholder: asks for the office folder. The setup dialog unit replaces it.
private struct OfficeSheet: View {
    @Environment(AppState.self) private var state

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Choose your office folder")
                .font(.title2.weight(.semibold))
            Text(
                "Family Office keeps everything in one folder on this Mac. Choose an existing "
                    + "office, or create an empty folder and set it up from the dashboard."
            )
            .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Not Now") {
                    state.setOffice(nil)
                }
                Spacer()
                Button("Choose Folder…") {
                    state.chooseOffice()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 440)
    }
}
