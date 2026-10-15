"""The fo serve HTTP server: gating, JSON routes, static files, and streaming responses."""

import html
import json
import mimetypes
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from fo import __version__
from fo.envelope import FAILED, encode, failure
from fo.errors import OfficeError
from fo.serve import onboarding
from fo.serve.auth import Access, Denial
from fo.serve.cache import ResponseCache
from fo.serve.routes_read import DOCTOR_TTL, resolve

STATUS = {
    "office_not_found": 404,
    "unknown_report": 404,
    "unknown_profile": 404,
    "unknown_route": 404,
    "office_locked": 409,
    "invalid_transition": 409,
    "office_already_open": 409,
}
MAX_BODY = 64 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def static_root():
    return Path(str(files("fo").joinpath("data", "app")))


def page(title, message):
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{html.escape(title)}</title>"
        "<body style='font:16px system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='font-size:1.25rem'>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
    )


class Locator:
    """The office the server reads, re-checked on every request so setup needs no restart."""

    def __init__(self, path=None):
        self.path = Path(path).expanduser().resolve() if path else None

    def candidate(self):
        return self.path

    def root(self):
        path = self.path
        if path and (path / "office.toml").is_file() and (path / "profile").is_dir():
            return path
        raise OfficeError("office_not_found", "No office yet; follow the setup steps.")


@dataclass
class App:
    locator: Locator
    access: Access = field(default_factory=Access)
    read_only: bool = False
    static: Path = field(default_factory=static_root)
    cache: ResponseCache = field(default_factory=ResponseCache)
    heartbeat_interval: float = 15.0
    heartbeat_limit: int | None = None
    log_lines: list | None = None

    def log(self, line):
        stamp = datetime.now().strftime("%H:%M:%S")
        if self.log_lines is not None:
            self.log_lines.append(line)
        else:
            print(f"{stamp} {line}", file=sys.stderr, flush=True)

    def status(self, headers):
        from fo.operations import status

        try:
            office = status(self.locator.root(), read_only=True)
        except OfficeError:
            office = None
        return {
            "version": __version__,
            "mode": "office" if office else "onboarding",
            "read_only": self.read_only,
            "remote": self.access.remote,
            "identity": self.access.identity(headers),
            "office": office,
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "fo-serve"
    sys_version = ""

    @property
    def app(self) -> App:
        return self.server.app

    # The default log line carries the request line, which may carry the landing token.
    def log_request(self, code="-", size="-"):
        path = urlsplit(getattr(self, "path", "")).path or "-"
        self.app.log(f"{getattr(self, 'command', '-')} {path} {code}")

    def log_error(self, format, *args):
        self.app.log("rejected malformed request")

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def send(self, status, body, content_type, headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, value):
        self.send(status, encode(value), "application/json; charset=utf-8")

    def send_page(self, status, title, message, headers=None):
        self.send(status, page(title, message), "text/html; charset=utf-8", headers)

    def deny(self, denial: Denial, api):
        if api:
            self.send_json(denial.status, {"reason": denial.reason, "message": denial.message})
        else:
            self.send_page(denial.status, "Family Office", denial.message)

    def dispatch(self, method):
        url = urlsplit(self.path)
        query = dict(parse_qsl(url.query, keep_blank_values=True))
        api = url.path.startswith("/api/")
        denial = self.app.access.check_host(self.headers)
        if denial:
            return self.deny(denial, api)
        if method == "GET" and url.path == "/" and "t" in query:
            return self.landing(query["t"])
        denial = self.app.access.check(method, self.headers)
        if denial:
            return self.deny(denial, api)
        try:
            if api:
                self.api(method, url.path, query)
            elif method == "GET":
                self.static(url.path)
            else:
                raise OfficeError("unknown_route", "No such route.")
        except OfficeError as exc:
            self.send_json(STATUS.get(exc.reason, 400), failure(exc))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - never leak text, paths, or credentials
            self.app.log(f"{method} {url.path} failed: {type(exc).__name__}")
            self.send_json(500, dict(FAILED))

    def landing(self, token):
        if not self.app.access.valid_token(token):
            return self.send_page(
                401, "Family Office", "This link has expired. Open the URL fo serve printed."
            )
        # A same-origin refresh carries the SameSite=Strict cookie even when the link was
        # opened from another site, where a redirect response would not.
        self.send(
            200,
            "<!doctype html><meta charset=utf-8><meta http-equiv=refresh content='0; url=/'>"
            "<title>Family Office</title><a href='/'>Continue to Family Office</a>",
            "text/html; charset=utf-8",
            {"Set-Cookie": self.app.access.cookie_header()},
        )

    def body(self):
        """A JSON object from a same-origin request; anything else is refused unread."""
        if self.headers.get_content_type() != "application/json":
            raise OfficeError("invalid_request", "Send a JSON object.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BODY:
            raise OfficeError("invalid_request", "Send a JSON object under 64 KiB.")
        try:
            value = json.loads(self.rfile.read(length))
        except ValueError as exc:
            raise OfficeError("invalid_request", "Send a JSON object.") from exc
        if not isinstance(value, dict):
            raise OfficeError("invalid_request", "Send a JSON object.")
        return value

    def api(self, method, path, query):
        if method == "POST":
            if path not in POSTS:
                raise OfficeError("unknown_route", "No such route.")
            return self.send_json(200, POSTS[path](self.app, self.body()))
        if method != "GET":
            raise OfficeError("unknown_route", "No such route.")
        if path == "/api/status":
            return self.send_json(200, self.app.status(self.headers))
        if path == "/api/onboarding":
            return self.send_json(200, onboarding.derive(self.app.locator))
        if path == "/api/heartbeat":
            return self.stream(self.heartbeat())
        route, params = resolve(path)
        if route is None:
            raise OfficeError("unknown_route", "No such route.")
        query = {**query, **params}
        if not route.office:
            return self.send_json(200, route.handler(None, query))
        root = self.app.locator.root()
        if route.cache == "never":
            value = route.handler(root, query)
        else:
            key = (path, tuple(sorted(query.items())))
            ttl = DOCTOR_TTL if route.cache == "ttl" else None
            value = self.app.cache.get(root, key, lambda: route.handler(root, query), ttl)
        self.send_json(200, value)

    def heartbeat(self):
        count = 0
        while self.app.heartbeat_limit is None or count < self.app.heartbeat_limit:
            count += 1
            yield {"event": "heartbeat", "sequence": count}
            time.sleep(self.app.heartbeat_interval)

    def stream(self, events):
        """Server-sent events written as they happen; closing the connection ends the stream."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        for event in events:
            self.wfile.write(f"data: {encode(event)}\n\n".encode())
            self.wfile.flush()

    def static(self, path):
        base = self.app.static.resolve()
        relative = unquote(path).lstrip("/") or "index.html"
        target = base / relative
        if "\x00" in relative or not target.resolve().is_relative_to(base):
            raise OfficeError("unknown_route", "No such file.")
        if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(base)):
            raise OfficeError("unknown_route", "No such file.")
        if target.is_dir():
            raise OfficeError("unknown_route", "No such file.")
        if not target.is_file():
            # Client-side routes such as /finances load the app shell.
            if relative != "index.html" and "." in Path(relative).name:
                raise OfficeError("unknown_route", "No such file.")
            target = base / "index.html"
            if not target.is_file():
                return self.send_page(
                    503, "Family Office", "The app build is missing; reinstall family-office."
                )
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith("javascript"):
            content_type += "; charset=utf-8"
        self.send(200, target.read_bytes(), content_type)


def choose_office(app, body):
    onboarding.choose(app.locator, body.get("path"))
    return onboarding.derive(app.locator)


POSTS = {"/api/onboarding/path": choose_office}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)
        app.access.port = self.server_address[1]


def make_server(app, host="127.0.0.1", port=0):
    return Server((host, port), app)


def start_in_thread(app, host="127.0.0.1", port=0):
    """For tests and embedding: a running server and its thread."""
    server = make_server(app, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
