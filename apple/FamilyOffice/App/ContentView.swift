import AppKit
import FOKit
import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var state
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        @Bindable var state = state
        ZStack(alignment: .top) {
            if let handshake = state.handshake {
                WebView(
                    handshake: handshake,
                    generation: state.pageGeneration,
                    dataStore: state.websiteDataStore,
                    onLoad: { cookies in state.pageLoaded(cookies: cookies) },
                    onAction: { action in perform(action) }
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
        .sheet(item: $state.setup) { model in
            SetupDialog(model: model)
                .interactiveDismissDisabled()
        }
        #if DEBUG
        // Development walkthroughs: `-openSettingsOnLaunch YES`, optionally with
        // `-settingsTab devices`, opens Settings without clicking.
        .task {
            if UserDefaults.standard.bool(forKey: "openSettingsOnLaunch") {
                openSettings()
            }
        }
        #endif
    }
}

extension ContentView {
    /// A button on the page asked for one of the app's own windows.
    fileprivate func perform(_ action: WebAction) {
        switch action {
        case .setup:
            state.openSetup(manual: true)
        case .settings(let tab):
            UserDefaults.standard.set(tab, forKey: SettingsView.tabKey)
            openSettings()
            NSApp.activate(ignoringOtherApps: true)
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
