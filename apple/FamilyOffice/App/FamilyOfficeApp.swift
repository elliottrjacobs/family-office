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
