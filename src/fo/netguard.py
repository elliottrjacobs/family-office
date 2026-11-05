"""The URL deny list shared by `fo research fetch`, the run guard, and tests.

`reject(url)` returns a stable reason code, or None when the URL may be fetched. It refuses
anything that could reach this machine, the local network, or the tailnet: a run must not
reach `fo serve`, other local services, or another device through a fetch.

The host is resolved once and refused if any returned address is blocked, so a name with
one public and one private address is refused. A caller that then connects resolves again;
a DNS answer that changes between the two lookups is an accepted residual risk recorded in
docs/development/research-providers.md.
"""

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

REASONS = {
    "unsupported_scheme": "Only http and https URLs can be fetched.",
    "credentials_in_url": "URLs carrying a user name or password are refused.",
    "missing_host": "The URL has no host.",
    "localhost_host": "localhost names are refused.",
    "tailnet_host": "Tailscale (.ts.net) hosts are refused.",
    "unresolvable_host": "The host does not resolve.",
    "loopback_address": "The host resolves to a loopback address.",
    "link_local_address": "The host resolves to a link-local address.",
    "private_address": "The host resolves to a private network address.",
    "cgnat_address": "The host resolves to a shared (CGNAT or tailnet) address.",
    "ula_address": "The host resolves to an IPv6 unique local address.",
    "unspecified_address": "The host resolves to the unspecified address.",
    "reserved_address": "The host resolves to a multicast or reserved address.",
}

CGNAT = ipaddress.ip_network("100.64.0.0/10")
ULA = ipaddress.ip_network("fc00::/7")
PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]

Resolver = Callable[[str], Iterable[str]]


def resolve(host: str) -> list[str]:
    """Every address the system resolver returns for host; empty when it does not resolve."""
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return [str(answer[4][0]) for answer in answers]


def address_reason(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return "unresolvable_host"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_unspecified:
        return "unspecified_address"
    if address.is_loopback:
        return "loopback_address"
    if address.is_link_local:
        return "link_local_address"
    if address.version == 4 and address in CGNAT:
        return "cgnat_address"
    if address.version == 4 and any(address in network for network in PRIVATE):
        return "private_address"
    if address.version == 6 and address in ULA:
        return "ula_address"
    if address.is_multicast or address.is_reserved or address.is_private or not address.is_global:
        return "reserved_address"
    return None


def reject(url: str, resolver: Resolver | None = None) -> str | None:
    """A reason code from REASONS when url must not be fetched, else None."""
    try:
        parts = urlsplit(str(url).strip())
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return "missing_host"
    if parts.scheme.lower() not in ("http", "https"):
        return "unsupported_scheme"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "credentials_in_url"
    if not host:
        return "missing_host"
    host = host.rstrip(".").lower()
    if not host:
        return "missing_host"
    if host == "localhost" or host.endswith(".localhost"):
        return "localhost_host"
    if host == "ts.net" or host.endswith(".ts.net"):
        return "tailnet_host"
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        addresses = [host]
    except ValueError:
        addresses = list((resolver or resolve)(host))
    if not addresses:
        return "unresolvable_host"
    for address in addresses:
        reason = address_reason(address)
        if reason:
            return reason
    return None
