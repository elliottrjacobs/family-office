"""fo serve: an optional companion web app for one office, on loopback by default.

Never import fo.cli here: importing it builds the Typer app as a side effect.
"""

import ipaddress
import os
import signal
import sys
import threading
import webbrowser
from pathlib import Path

from fo.config import read_config
from fo.errors import OfficeError
from fo.office import discover

DEFAULT_PORT = 4790
# The Schwab OAuth callback listens on 8182.
RESERVED_PORTS = {8182}


def settings(root):
    if root is None:
        return {}
    value = read_config(root).get("serve", {})
    if not isinstance(value, dict):
        raise OfficeError("invalid_config", "[serve] in office.toml must be a table.")
    logins = value.get("allowed_logins", [])
    if not isinstance(logins, list) or not all(isinstance(v, str) for v in logins):
        raise OfficeError("invalid_config", "[serve] allowed_logins must be a list of logins.")
    if not isinstance(value.get("tailnet_name", ""), str):
        raise OfficeError("invalid_config", "[serve] tailnet_name must be text.")
    return value


def loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def prepare(office=None, port=None, host=None, remote=False, read_only=False):
    """Validate options and bind; returns the server and the lines to print."""
    # Imported here so the run guard hook, also in this package, starts quickly.
    from fo.serve.auth import Access
    from fo.serve.runner_claude import DEEP, ClaudeRunner
    from fo.serve.runs import RunManager
    from fo.serve.server import App, Locator, make_server

    explicit = office or os.environ.get("FO_OFFICE")
    if explicit:
        candidate = Path(explicit)
    else:
        try:
            candidate = discover(None)
        except OfficeError:
            candidate = None
    locator = Locator(candidate)
    try:
        root = locator.root()
    except OfficeError:
        root = None
    config = settings(root)
    port = port if port is not None else config.get("port", DEFAULT_PORT)
    # Port 0 asks the system for any free port.
    if not isinstance(port, int) or not 0 <= port <= 65535 or port in RESERVED_PORTS:
        raise OfficeError("invalid_port", "Choose a port from 1 to 65535 other than 8182.")
    bind = host or "127.0.0.1"
    tailnet = config.get("tailnet_name", "")
    if remote and not tailnet:
        raise OfficeError("invalid_config", "Set [serve] tailnet_name in office.toml for --remote.")
    access = Access(
        bound=bind,
        remote=remote,
        tailnet_name=tailnet,
        allowed_logins=list(config.get("allowed_logins", [])),
    )
    runs = None if read_only else RunManager(ClaudeRunner(), deep=DEEP)
    app = App(locator, access, read_only, runs=runs)
    try:
        server = make_server(app, bind, port)
    except OSError as exc:
        raise OfficeError("port_unavailable", f"Port {port} is unavailable; pass --port.") from exc
    lines = []
    if not loopback(bind):
        lines.append(
            f"Warning: listening on {bind}, beyond this machine. Anyone who can reach it "
            "and obtains the link can read the office; prefer tailscale serve."
        )
    lines.append("Family Office companion app")
    lines.append(f"  Open: {access.landing_url()}")
    if remote:
        lines.append(f"  Tailnet: https://{tailnet}/?t={access.token}")
    lines.append(f"  Office: {root}" if root else "  No office yet; the page will guide setup.")
    lines.append("  Press Enter to print the link again, Ctrl-C to stop.")
    return server, lines


def interrupt(signum, frame):
    raise KeyboardInterrupt


def serve(office=None, port=None, host=None, remote=False, open_browser=False, read_only=False):
    server, lines = prepare(office, port, host, remote, read_only)
    if threading.current_thread() is threading.main_thread():
        # A service manager stops the server with SIGTERM; it ends runs like Ctrl-C does.
        signal.signal(signal.SIGTERM, interrupt)
    for line in lines:
        print(line, flush=True)
    link = server.app.access.landing_url()
    if sys.stdin and sys.stdin.isatty():

        def reprint():
            for _ in sys.stdin:
                print(f"  Open: {link}", flush=True)

        threading.Thread(target=reprint, daemon=True).start()
    if open_browser:
        webbrowser.open(link)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # An advisor run outliving the server would keep spending its budget unwatched.
        if server.app.runs is not None:
            server.app.runs.shutdown()
        server.server_close()
    return "Stopped."
