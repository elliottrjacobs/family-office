import FOKit
import Foundation
import WebKit

/// Gets the session cookie for a new server without the main window: an off-screen web view
/// on the app's non-persistent data store loads the landing URL once, hands over the cookies,
/// and is discarded. The menu bar and Settings keep working after a restart while the main
/// window is closed. The token stays inside WebKit, exactly as in the visible web view.
@MainActor
final class SessionPrimer: NSObject, WKNavigationDelegate {
    private var webView: WKWebView?
    private var completion: (@MainActor ([HTTPCookie]) -> Void)?
    private var port: Int?

    func prime(
        _ handshake: Handshake, store: WKWebsiteDataStore,
        completion: @escaping @MainActor ([HTTPCookie]) -> Void
    ) {
        cancel()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = store
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        self.webView = webView
        self.completion = completion
        self.port = handshake.port
        webView.load(URLRequest(url: handshake.landingURL))
    }

    func cancel() {
        webView?.stopLoading()
        webView?.navigationDelegate = nil
        webView = nil
        completion = nil
        port = nil
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        // Only the landing page itself; the dashboard it refreshes to is not needed here.
        let url = navigationAction.request.url
        let isLanding = url?.host == "127.0.0.1" && url?.port == port && url?.query?.contains("t=") == true
        decisionHandler(isLanding ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView === self.webView else { return }
        webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { [weak self] cookies in
            guard let self, webView === self.webView else { return }
            let completion = self.completion
            self.cancel()
            completion?(cookies)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if webView === self.webView { cancel() }
    }

    func webView(
        _ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: Error
    ) {
        if webView === self.webView { cancel() }
    }
}
