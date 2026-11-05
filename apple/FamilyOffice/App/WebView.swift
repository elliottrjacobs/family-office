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
struct WebView: NSViewRepresentable {
    let handshake: Handshake
    let generation: Int
    let dataStore: WKWebsiteDataStore
    let onLoad: @MainActor ([HTTPCookie]) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onLoad: onLoad)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = dataStore
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.onLoad = onLoad
        guard context.coordinator.loadedGeneration != generation else { return }
        context.coordinator.loadedGeneration = generation
        webView.load(URLRequest(url: handshake.landingURL))
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var loadedGeneration: Int?
        var onLoad: @MainActor ([HTTPCookie]) -> Void

        init(onLoad: @escaping @MainActor ([HTTPCookie]) -> Void) {
            self.onLoad = onLoad
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
