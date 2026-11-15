import AppKit
import FOKit
import SwiftUI
import WebKit

/// The React app served by `fo serve`, in a WKWebView.
///
/// - The website data store is the app's per-launch non-persistent store, so the session
///   cookie never reaches disk and dies with the app.
/// - It loads the handshake's landing URL, which sets the cookie the normal way, and loads it
///   again whenever `generation` changes (a new server after a restart, or View > Reload).
/// - Only loopback pages load inside; any other link opens in the default browser.
/// - The page can ask the app to open one of its own windows through the `familyOffice`
///   message handler (`WebAction`): the setup dialog or a Settings pane. Nothing else is
///   reachable from the page, and no value passes back to it.
struct WebView: NSViewRepresentable {
    let handshake: Handshake
    let generation: Int
    let dataStore: WKWebsiteDataStore
    let onLoad: @MainActor ([HTTPCookie]) -> Void
    let onAction: @MainActor (WebAction) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onLoad: onLoad, onAction: onAction)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = dataStore
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        // A weak proxy: the content controller retains its handler, and the coordinator
        // must be free to go away with the view.
        configuration.userContentController.add(
            WeakMessageHandler(context.coordinator), name: WebAction.handlerName)
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.onLoad = onLoad
        context.coordinator.onAction = onAction
        guard context.coordinator.loadedGeneration != generation else { return }
        context.coordinator.loadedGeneration = generation
        webView.load(URLRequest(url: handshake.landingURL))
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        var loadedGeneration: Int?
        var onLoad: @MainActor ([HTTPCookie]) -> Void
        var onAction: @MainActor (WebAction) -> Void

        init(
            onLoad: @escaping @MainActor ([HTTPCookie]) -> Void,
            onAction: @escaping @MainActor (WebAction) -> Void
        ) {
            self.onLoad = onLoad
            self.onAction = onAction
        }

        /// A request from the page: only from the main frame of a loopback page, and only
        /// one of the actions `WebAction` knows.
        func userContentController(
            _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
        ) {
            guard message.frameInfo.isMainFrame,
                let url = message.frameInfo.request.url, Self.isLoopback(url),
                let body = message.body as? [String: Any],
                let action = WebAction(body["action"] as? String)
            else { return }
            onAction(action)
        }

        static func isLoopback(_ url: URL) -> Bool {
            guard url.scheme == "http" || url.scheme == "https" else { return false }
            return ["127.0.0.1", "localhost", "::1", "[::1]"].contains(url.host ?? "")
        }

        func webView(
            _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                return decisionHandler(.cancel)
            }
            if Self.isLoopback(url) || url.scheme == "about" || url.scheme == "blob"
                || url.scheme == "data"
            {
                return decisionHandler(.allow)
            }
            if navigationAction.targetFrame?.isMainFrame ?? true,
                ["http", "https", "mailto"].contains(url.scheme ?? "")
            {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        }

        /// `target=_blank` and `window.open`: loopback pages stay in this view, others go to
        /// the default browser. No second web view is ever created.
        func webView(
            _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if let url = navigationAction.request.url {
                if Self.isLoopback(url) {
                    webView.load(URLRequest(url: url))
                } else if ["http", "https", "mailto"].contains(url.scheme ?? "") {
                    NSWorkspace.shared.open(url)
                }
            }
            return nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard let url = webView.url, Self.isLoopback(url) else { return }
            webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { [weak self] cookies in
                self?.onLoad(cookies)
            }
        }
    }
}

/// Keeps the content controller from retaining the coordinator.
private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: (any WKScriptMessageHandler)?

    init(_ target: any WKScriptMessageHandler) {
        self.target = target
    }

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
    ) {
        target?.userContentController(userContentController, didReceive: message)
    }
}
