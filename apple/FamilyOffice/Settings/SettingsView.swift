import SwiftUI

/// The Settings window (Family Office > Settings…, or Settings… in the menu bar item).
struct SettingsView: View {
    var body: some View {
        TabView {
            GeneralSettings()
                .tabItem { Label("General", systemImage: "gearshape") }
            AdvancedSettings()
                .tabItem { Label("Advanced", systemImage: "slider.horizontal.3") }
        }
        .frame(width: 560, height: 520)
    }
}
