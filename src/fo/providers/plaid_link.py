"""Plaid Link on a one-time loopback page, so linking needs no hosted backend.

`fo auth plaid` creates the Link token with the user's own credentials, then serves a
page on 127.0.0.1 at a random path that loads Plaid's Link web SDK from cdn.plaid.com.
Link posts its public token back to the same page; the CLI exchanges it with Plaid
directly. The server answers only its own host and origin, accepts one result, logs
nothing, and stops as soon as Link finishes, is closed, or times out.
"""

import html
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fo.errors import OfficeError
from fo.providers.plaid import ENVIRONMENTS
from fo.providers.text import untrusted_text

SDK = "https://cdn.plaid.com/link/v2/stable/link-initialize.js"
TIMEOUT = 900
MAX_BODY = 16384

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Family Office: link an institution</title>
<style nonce="{nonce}">
body {{ font: 16px/1.5 -apple-system, BlinkMacSystemFont, sans-serif; margin: 3rem auto;
  max-width: 32rem; padding: 0 1rem; color: #1d1d1f; background: #fff; }}
@media (prefers-color-scheme: dark) {{ body {{ color: #f5f5f7; background: #1d1d1f; }} }}
button {{ font: inherit; padding: .5rem 1rem; }}
</style>
</head>
<body>
<h1>Link an institution</h1>
<p id="status">Opening Plaid Link&hellip;</p>
<p><button id="open" type="button">Open Plaid Link again</button></p>
<script nonce="{nonce}" src="{sdk}"></script>
<script nonce="{nonce}">
const status = document.getElementById("status");
let sent = false;
function send(body, text) {{
  if (sent) return;
  sent = true;
  fetch({finish}, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify(body),
  }}).then(
    () => {{ status.textContent = text; document.getElementById("open").hidden = true; }},
    () => {{ status.textContent = "The terminal stopped listening. Run fo auth plaid again."; }},
  );
}}
const handler = Plaid.create({{
  token: {token},
  onSuccess: (public_token, metadata) => send(
    {{status: "success", public_token, institution: metadata.institution || null}},
    "Linked. You can close this tab and return to Family Office.",
  ),
  onExit: (error) => {{
    if (error) {{ status.textContent = "Link closed with an error. Try again, or close this tab."; return; }}
    send({{status: "exit"}}, "Link closed. Nothing was connected; you can close this tab.");
  }},
}});
document.getElementById("open").addEventListener("click", () => handler.open());
handler.open();
</script>
</body>
</html>
"""


def script_json(value):
    """JSON safe inside an inline script."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def run_link(link_token, environment, opener=webbrowser.open, announce=None, timeout=TIMEOUT):
    """Serve Link once and return Link's result; raises when it is closed or times out."""
    if environment not in ENVIRONMENTS:
        raise OfficeError("invalid_credentials", "Plaid environment is sandbox or production.")
    path = "/" + secrets.token_urlsafe(24)
    finish = path + "/finish"
    result = {}
    done = threading.Event()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "fo"
        sys_version = ""

        def log_message(self, *args):
            # Request lines carry the session path; nothing is logged.
            return

        def origin(self):
            return f"http://127.0.0.1:{self.server.server_address[1]}"

        def reply(self, status, body=b"", kind="text/plain; charset=utf-8", headers=()):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def trusted(self):
            return self.headers.get("Host") == self.origin().removeprefix("http://")

        def do_GET(self):
            if not self.trusted() or self.path != path:
                return self.reply(404)
            nonce = secrets.token_urlsafe(16)
            page = PAGE.format(
                nonce=nonce,
                sdk=html.escape(SDK),
                finish=script_json(finish),
                token=script_json(link_token),
            ).encode()
            policy = "; ".join(
                (
                    "default-src https://cdn.plaid.com/",
                    f"script-src 'nonce-{nonce}' {SDK}",
                    f"style-src 'nonce-{nonce}'",
                    f"style-src-elem 'nonce-{nonce}'",
                    "style-src-attr 'unsafe-inline'",
                    "frame-src https://cdn.plaid.com/",
                    f"connect-src 'self' {ENVIRONMENTS[environment]}/",
                    "img-src https://cdn.plaid.com/ data:",
                    "base-uri 'none'",
                    "form-action 'none'",
                )
            )
            self.reply(
                200,
                page,
                "text/html; charset=utf-8",
                [("Content-Security-Policy", policy), ("X-Frame-Options", "DENY")],
            )

        def do_POST(self):
            if (
                not self.trusted()
                or self.path != finish
                or self.headers.get("Origin") != self.origin()
                or not (self.headers.get("Content-Type") or "").startswith("application/json")
            ):
                return self.reply(404)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_BODY:
                    raise ValueError("size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or body.get("status") not in {"success", "exit"}:
                    raise ValueError("shape")
            except (ValueError, UnicodeDecodeError):
                return self.reply(400)
            with lock:
                if result:
                    return self.reply(409)
                result.update(body)
            # Answer the page before the server stops listening.
            self.reply(204)
            done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}{path}"
        if announce:
            announce(f"Opening Plaid Link in your browser. If it does not open, visit {url}")
        try:
            opener(url)
        except Exception:  # noqa: BLE001 - a missing browser leaves the printed URL.
            pass
        finished = done.wait(timeout)
    finally:
        server.shutdown()
        server.server_close()
    if not finished:
        raise OfficeError(
            "link_timeout", "Plaid Link was not finished in time; run fo auth plaid again."
        )
    if result.get("status") != "success":
        raise OfficeError("link_cancelled", "Plaid Link was closed before an institution linked.")
    token = result.get("public_token")
    if (
        not isinstance(token, str)
        or not token.startswith("public-")
        or len(token) > 256
        or not token.isprintable()
    ):
        raise OfficeError("provider_error", "Plaid Link returned an unusable result.")
    institution = result.get("institution") if isinstance(result.get("institution"), dict) else {}
    name = institution.get("name")
    ident = institution.get("institution_id")
    return {
        "public_token": token,
        "institution": untrusted_text(name)[:120] if isinstance(name, str) else None,
        "institution_id": ident if isinstance(ident, str) and len(ident) <= 64 else None,
    }
