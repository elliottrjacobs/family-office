"""Reject personal identifiers in the public Git tree: tailnet names, CGNAT addresses, UDIDs, home paths."""

import ipaddress
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

PLACEHOLDER_HOSTS = {"machine.your-tailnet.ts.net", "example-mac.tail0000.ts.net"}
PLACEHOLDER_TAILNET = "tail0000.ts.net"
CGNAT = ipaddress.ip_network("100.64.0.0/10")
CGNAT_ALLOWED = {
    "src/fo/netguard.py",
    "docs/development/research-providers.md",
    "SECURITY.md",
    # The tests that exercise the network guard and the synthetic `tailscale status` fixture.
    "tests/test_netguard.py",
    "tests/test_research.py",
    "tests/test_serve_guard.py",
    "apple/FOKit/Tests/FOKitTests/Fixtures/tailscale-status.json",
}
SKIP_NAMES = {"uv.lock", "package-lock.json", "Package.resolved"}
# docs/plans/ is preserved as written; its examples use invented tailnet values.
SKIP_PREFIXES = ("src/fo/data/app/assets/", "docs/plans/")

TS_NET = re.compile(r"(?<![\w.*-])((?:[A-Za-z0-9][A-Za-z0-9-]*\.)+ts\.net)\b", re.I)
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
UDID = re.compile(r"(?<![0-9A-Za-z-])[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}(?![0-9A-Za-z-])")
HOME_PATH = re.compile(r"/Users/(?!<)[A-Za-z0-9._-]+/")


def skipped(path):
    pure = PurePosixPath(path)
    return path.startswith(SKIP_PREFIXES) or pure.name in SKIP_NAMES or "node_modules" in pure.parts


def cgnat_allowed(path):
    return path in CGNAT_ALLOWED


def scan_text(path, text):
    """Return `path:line: reason` strings for one file's text."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in TS_NET.finditer(line):
            host = match.group(1).lower()
            if host not in PLACEHOLDER_HOSTS and host != PLACEHOLDER_TAILNET:
                hits.append(f"{path}:{number}: tailnet hostname {host} is not a placeholder")
        if not cgnat_allowed(path):
            for match in IPV4.finditer(line):
                try:
                    address = ipaddress.ip_address(match.group(1))
                except ValueError:
                    continue
                if address in CGNAT:
                    hits.append(f"{path}:{number}: CGNAT (tailnet range) address {address}")
        if UDID.search(line):
            hits.append(f"{path}:{number}: UDID-shaped identifier")
        if HOME_PATH.search(line):
            hits.append(f"{path}:{number}: absolute home-directory path")
    return hits


def scan_file(path, root):
    try:
        data = (root / path).read_bytes()
    except OSError:
        return []
    if b"\0" in data:
        return []
    return scan_text(path, data.decode("utf-8", errors="ignore"))


def violations(paths, root=Path(".")):
    hits = []
    for path in paths:
        if path and not skipped(path):
            hits.extend(scan_file(path, root))
    return hits


if __name__ == "__main__":
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    found = violations(tracked)
    for hit in found:
        print(hit)
    sys.exit(1 if found else 0)
