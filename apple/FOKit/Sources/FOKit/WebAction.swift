import Foundation

/// What the dashboard page may ask the Mac app to do, through the web view's
/// `familyOffice` message handler: open the setup dialog, or open Settings on one pane.
/// The page shows these as buttons where a step needs one of the app's own windows, such
/// as connecting an account. Anything else the page sends is ignored.
public enum WebAction: Sendable, Equatable {
    case setup
    case settings(tab: String)

    /// The name the page posts to: `window.webkit.messageHandlers.familyOffice`.
    public static let handlerName = "familyOffice"

    /// The Settings panes the page may open, by the tab's tag.
    public static let tabs = ["general", "engines", "connectors", "devices", "advanced"]

    /// Parses `"setup"` and `"settings:<tab>"`; nil for anything else.
    public init?(_ text: String?) {
        guard let text else { return nil }
        if text == "setup" {
            self = .setup
            return
        }
        let parts = text.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2, parts[0] == "settings", Self.tabs.contains(parts[1]) else { return nil }
        self = .settings(tab: parts[1])
    }
}
