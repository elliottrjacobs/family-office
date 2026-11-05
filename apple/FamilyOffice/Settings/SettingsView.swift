import SwiftUI
import os

/// The Settings window (Family Office > Settings…, or Settings… in the menu bar item).
struct SettingsView: View {
    /// `UserDefaults` key for the last tab shown; `-settingsTab devices` opens a given tab.
    static let tabKey = "settingsTab"

    @AppStorage(SettingsView.tabKey) private var tab = "general"

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
    }
}

/// State changes in the panes, for development walkthroughs: kinds and counts only, never
/// names, paths, codes or tokens.
let settingsLog = Logger(subsystem: "com.familyoffice.app", category: "settings")
