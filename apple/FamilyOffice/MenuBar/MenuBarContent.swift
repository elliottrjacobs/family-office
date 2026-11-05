import AppKit
import FOKit
import SwiftUI
import os

/// The menu bar item's menu: office, sync age, a run in progress, phone reachability, then
/// Open Family Office, Restart Server, Settings… and Quit.
struct MenuBarContent: View {
    @Environment(AppState.self) private var state
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        let monitor = state.monitor
        Text(state.officeTitle)
        if let line = state.serverLine {
            Text(line)
        } else {
            Text(OfficeSummary.syncLine(monitor.status))
            if let run = OfficeSummary.runLine(monitor.runs) {
                Text(run)
            }
            if let phone = OfficeSummary.phoneLine(monitor.devices ?? []) {
                Text(phone)
            }
            if state.power.assertionHeld {
                Text("Keeping this Mac awake")
            }
        }
        Divider()
        Button("Open Family Office") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        Button("Restart Server") {
            state.restartServer()
        }
        .disabled(state.officePath == nil && !state.serverRunning)
        SettingsLink {
            Text("Settings…")
        }
        .keyboardShortcut(",")
        Divider()
        Button("Quit Family Office") {
            NSApp.terminate(nil)
        }
        .keyboardShortcut("q")
    }
}

/// The menu bar icon; it dims while the server is not running.
struct MenuBarLabel: View {
    @Environment(AppState.self) private var state

    var body: some View {
        Image(systemName: state.serverState == .running ? "building.columns.fill" : "building.columns")
            .accessibilityLabel("Family Office")
            .onAppear {
                Logger(subsystem: "com.familyoffice.app", category: "monitor")
                    .info("menu bar item shown")
            }
    }
}
