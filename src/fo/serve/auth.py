"""Access control for fo serve: a per-launch token cookie plus Host and Origin checks.

Loopback is reachable by DNS-rebinding pages and by other OS users, so every route needs
the cookie in every mode. Tailscale identity headers only narrow access in remote mode;
any local process can send them, so they never grant access on their own.
"""

import hmac
import secrets
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie

COOKIE = "fo_session"
LOGIN_HEADER = "Tailscale-User-Login"
NAME_HEADER = "Tailscale-User-Name"
LOOPBACK_NAMES = ("127.0.0.1", "localhost")


@dataclass
class Denial:
    status: int
    reason: str
    message: str


@dataclass
class Access:
    port: int = 0
    bound: str = "127.0.0.1"
    remote: bool = False
    tailnet_name: str = ""
    allowed_logins: list[str] = field(default_factory=list)
    # Generated per process, so a restart rotates it and stale cookies stop working.
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))

    def hosts(self):
        names = {f"{name}:{self.port}" for name in LOOPBACK_NAMES}
        if self.bound not in ("127.0.0.1", "0.0.0.0", "::", "localhost"):
            names.add(f"{self.bound}:{self.port}")
        if self.remote and self.tailnet_name:
            names |= {self.tailnet_name, f"{self.tailnet_name}:443"}
        return names

    def origins(self):
        """The app's own origins; a browser omits the default port from Origin."""
        local = [h for h in self.hosts() if h.split(":")[0] != self.tailnet_name]
        result = {"http://" + h for h in local}
        if self.remote and self.tailnet_name:
            result.add("https://" + self.tailnet_name)
        return result

    def landing_url(self):
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def valid_token(self, value):
        return bool(value) and hmac.compare_digest(value.encode(), self.token.encode())

    def cookie_header(self):
        attributes = "HttpOnly; SameSite=Strict; Path=/"
        return f"{COOKIE}={self.token}; {attributes}" + ("; Secure" if self.remote else "")

    def check_host(self, headers):
        if headers.get("Host", "") not in self.hosts():
            return Denial(421, "misdirected_request", "Open the address fo serve printed.")
        return None

    def check_cookie(self, headers):
        try:
            cookie = SimpleCookie(headers.get("Cookie", ""))
        except CookieError:
            cookie = SimpleCookie()
        morsel = cookie.get(COOKIE)
        if not morsel or not self.valid_token(morsel.value):
            return Denial(
                401, "unauthorized", "Open the URL fo serve printed; a restart issues a new one."
            )
        return None

    def check_origin(self, method, headers):
        """Non-GET requests must come from the page's own origin."""
        if method == "GET":
            return None
        if headers.get("Origin") not in self.origins():
            return Denial(403, "forbidden_origin", "Requests must come from the companion app.")
        return None

    def identity(self, headers):
        if not self.remote:
            return None
        login = headers.get(LOGIN_HEADER)
        return {"login": login, "name": headers.get(NAME_HEADER)} if login else None

    def check_identity(self, headers):
        """With an allowlist, a missing or unlisted login fails closed; Funnel sends none."""
        if not self.remote or not self.allowed_logins:
            return None
        login = headers.get(LOGIN_HEADER)
        if login not in self.allowed_logins:
            return Denial(403, "forbidden_login", "This tailnet login is not allowed.")
        return None

    def check(self, method, headers):
        """Every gate after the landing route, in order: cookie, origin, identity."""
        return (
            self.check_cookie(headers)
            or self.check_origin(method, headers)
            or self.check_identity(headers)
        )
