import AppKit
import SwiftUI

@main
struct FamilyOfficeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        Window("Family Office", id: "main") {
            ContentView()
                .environment(delegate.state)
                .frame(minWidth: 900, minHeight: 600)
        }
        .commands {
            CommandGroup(after: .appInfo) {
                CheckForUpdatesButton(updater: delegate.state.updater)
            }
            CommandGroup(after: .newItem) {
                Button("Choose Office Folder…") {
                    delegate.state.chooseOffice()
                }
                .keyboardShortcut("o")
            }
            CommandGroup(after: .toolbar) {
                Button("Reload") {
                    delegate.state.reloadPage()
                }
                .keyboardShortcut("r")
                Button("Restart Server") {
                    delegate.state.restartServer()
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
            }
            CommandGroup(after: .help) {
                SetupMenuButton(state: delegate.state)
            }
        }

        Settings {
            SettingsView()
                .environment(delegate.state)
        }

        // The always-on part: status at a glance while the window is closed.
        MenuBarExtra {
            MenuBarContent()
                .environment(delegate.state)
        } label: {
            MenuBarLabel()
                .environment(delegate.state)
        }
        .menuBarExtraStyle(.menu)
    }
}

/// Family Office > Check for Updates…, under About in the app menu.
private struct CheckForUpdatesButton: View {
    let updater: Updater

    var body: some View {
        Button("Check for Updates…") {
            updater.checkForUpdates()
        }
        .disabled(!updater.configured || !updater.canCheckForUpdates)
    }
}

/// Help > Set Up Family Office…: brings the main window forward and opens the dialog.
private struct SetupMenuButton: View {
    let state: AppState
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Button("Set Up Family Office…") {
            openWindow(id: "main")
            state.openSetup(manual: true)
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let state = AppState()

    func applicationDidFinishLaunching(_ notification: Notification) {
        state.launch()
    }

    /// The menu bar item keeps the app, and so the server, running with no window open;
    /// Quit in the menu bar or the app menu stops both.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    /// The server must stop with the app: SIGTERM, up to five seconds, then SIGKILL.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard state.serverRunning else {
            state.power.release()
            return .terminateNow
        }
        Task {
            await state.shutdown()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
