import FOKit
import SwiftUI
import UIKit
import WebKit

/// The office's own web app, loaded from the Mac's tailnet address with the session cookie
/// that `DeviceSession.login()` received. The store is non-persistent, so the cookie lives
/// only as long as this view; the next launch logs in again with the Keychain token.
///
/// Links to other sites open in Safari. A 401 on any navigation means the Mac no longer
/// knows this phone, and `onUnauthorized` sends it back to pairing.
struct OfficeWebView: UIViewRepresentable {
    let url: URL
    let cookies: [HTTPCookie]
    let reloadToken: Int
    let onUnauthorized: (String?) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(host: url.host, onUnauthorized: onUnauthorized)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.defaultWebpagePreferences.preferredContentMode = .mobile
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true

        let refresh = UIRefreshControl()
        refresh.addTarget(
            context.coordinator, action: #selector(Coordinator.refresh(_:)), for: .valueChanged)
        webView.scrollView.refreshControl = refresh

        context.coordinator.reloadToken = reloadToken
        let store = configuration.websiteDataStore.httpCookieStore
        let cookies = self.cookies
        let request = URLRequest(url: url)
        Task { @MainActor in
            for cookie in cookies {
                await store.setCookie(cookie)
            }
            webView.load(request)
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.onUnauthorized = onUnauthorized
        if context.coordinator.reloadToken != reloadToken {
            context.coordinator.reloadToken = reloadToken
            webView.reload()
        }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let host: String?
        var onUnauthorized: (String?) -> Void
        var reloadToken = 0
        private var reported = false

        init(host: String?, onUnauthorized: @escaping (String?) -> Void) {
            self.host = host
            self.onUnauthorized = onUnauthorized
        }

        @objc func refresh(_ control: UIRefreshControl) {
            (control.superview?.superview as? WKWebView)?.reload()
            control.endRefreshing()
        }

        private func isOwn(_ url: URL) -> Bool {
            guard let scheme = url.scheme?.lowercased() else { return true }
            if scheme == "about" || scheme == "blob" || scheme == "data" { return true }
            return url.host == host && (scheme == "https" || scheme == "http")
        }

        func webView(
            _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction
        ) async -> WKNavigationActionPolicy {
            guard let url = navigationAction.request.url else { return .cancel }
            if isOwn(url) { return .allow }
            // Another site, a mail or phone link: hand it to the system (Safari for the web).
            await UIApplication.shared.open(url)
            return .cancel
        }

        func webView(
            _ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse
        ) async -> WKNavigationResponsePolicy {
            if let http = navigationResponse.response as? HTTPURLResponse, http.statusCode == 401 {
                if !reported {
                    reported = true
                    onUnauthorized(nil)
                }
                return .cancel
            }
            return .allow
        }

        /// `target="_blank"` links: open outside the app instead of in a new web view.
        func webView(
            _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if let url = navigationAction.request.url {
                if isOwn(url) {
                    webView.load(navigationAction.request)
                } else {
                    UIApplication.shared.open(url)
                }
            }
            return nil
        }
    }
}
