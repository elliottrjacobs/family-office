"""An in-process fo serve for tests, and a client that controls Host, Origin, and cookies."""

import hashlib
import http.client
import json
import socket
from contextlib import contextmanager

from fo.serve.server import App, Locator, start_in_thread


def tree(root):
    """Content and mode of every file under root, .git included."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            result[str(path.relative_to(root))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mode,
            )
    return result


def assert_unchanged(before, after):
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not changed, f"office files changed: {changed}"


def static_app(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text("<!doctype html><title>Family Office</title>")
    (directory / "assets").mkdir(exist_ok=True)
    (directory / "assets/app.js").write_text("console.log('app')\n")
    return directory


class Client:
    def __init__(self, server):
        self.port = server.server_address[1]
        self.token = server.app.access.token
        self.cookie = self.token

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    def request(self, method, path, body=None, headers=None, host=None, cookie=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        sent = {"Host": self.host if host is None else host}
        if cookie and self.cookie:
            sent["Cookie"] = f"fo_session={self.cookie}"
        if method != "GET":
            sent["Origin"] = f"http://{self.host}"
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        sent = {k: v for k, v in sent.items() if v is not None}
        payload = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, body=payload, headers=sent)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data

    def raw_post(self, path, payload):
        """POST bytes that are not JSON-encoded by this client."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Host": self.host,
            "Cookie": f"fo_session={self.cookie}",
            "Origin": f"http://{self.host}",
            "Content-Type": "application/json",
        }
        connection.request("POST", path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, dict(response.getheaders()), data

    def raw(self, data):
        """Send bytes as-is, for request lines http.client refuses to build."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as connection:
            connection.sendall(data)
            return connection.recv(65536)

    def get(self, path, **options):
        status, headers, data = self.request("GET", path, **options)
        return status, json.loads(data) if "json" in headers.get("content-type", "") else data

    def post(self, path, body=None, **options):
        status, headers, data = self.request("POST", path, body=body or {}, **options)
        return status, json.loads(data) if "json" in headers.get("content-type", "") else data


@contextmanager
def serving(root, tmp_path, **options):
    app = App(
        Locator(root),
        static=static_app(tmp_path / "static"),
        log_lines=[],
        heartbeat_interval=0,
        heartbeat_limit=3,
        **options,
    )
    server, _ = start_in_thread(app)
    try:
        yield app, Client(server)
    finally:
        server.shutdown()
        server.server_close()
