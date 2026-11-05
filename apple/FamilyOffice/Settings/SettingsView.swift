import SwiftUI
import os

/// The Settings window (Family Office > Settings…, or Settings… in the menu bar item).
struct SettingsView: View {
    /// `UserDefaults` key for the last tab shown; `-settingsTab devices` opens a given tab.
    static let tabKey = "settingsTab"

    @Environment(AppState.self) private var state
    @AppStorage(SettingsView.tabKey) private var tab = "general"
    @State private var debugTerminal: FoTerminalSession?

    var body: some View {
        TabView(selection: $tab) {
            GeneralSettings()
                .tabItem { Label("General", systemImage: "gearshape") }
                .tag("general")
            DevicesSettings()
                .tabItem { Label("Devices", systemImage: "iphone") }
                .tag("devices")
            AdvancedSettings()
                .tabItem { Label("Advanced", systemImage: "slider.horizontal.3") }
                .tag("advanced")
        }
        .frame(width: 560, height: 560)
        #if DEBUG
        // Development walkthroughs: `-terminalCommand "auth schwab"` opens the embedded
        // terminal with those words, so the refusal of anything outside the allowed set can
        // be checked (`-terminalCommand "bash"` is refused without starting a process).
        .task {
            if let words = UserDefaults.standard.string(forKey: "terminalCommand"), !words.isEmpty {
                debugTerminal = FoTerminalSession(
                    words: words.split(separator: " ").map(String.init), office: state.officePath)
            }
        }
        .sheet(item: $debugTerminal) { session in
            TerminalSheet(session: session) { debugTerminal = nil }
        }
        #endif
    }
}

/// State changes in the panes, for development walkthroughs: kinds and counts only, never
/// names, paths, codes or tokens.
let settingsLog = Logger(subsystem: "com.familyoffice.app", category: "settings")
