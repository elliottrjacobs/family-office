import pytest

from fo import netguard
from fo.netguard import REASONS, reject

PUBLIC = "93.184.215.14"


def answers(*addresses):
    def resolver(host):
        return list(addresses)

    return resolver


def no_dns(host):
    raise AssertionError("an IP literal or refused name must not be resolved")


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/hosts", "unsupported_scheme"),
        ("ftp://example.com/x", "unsupported_scheme"),
        ("javascript:alert(1)", "unsupported_scheme"),
        ("https://user:secret@example.com/", "credentials_in_url"),
        ("https://user@example.com/", "credentials_in_url"),
        ("https:///path", "missing_host"),
        ("http://localhost:4790/", "localhost_host"),
        ("http://LOCALHOST./", "localhost_host"),
        ("http://app.localhost/", "localhost_host"),
        ("http://machine.your-tailnet.ts.net/", "tailnet_host"),
        ("http://127.0.0.1:4790/", "loopback_address"),
        ("http://[::1]/", "loopback_address"),
        ("http://[::ffff:127.0.0.1]/", "loopback_address"),
        ("http://169.254.169.254/latest", "link_local_address"),
        ("http://[fe80::1]/", "link_local_address"),
        ("http://10.0.0.5/", "private_address"),
        ("http://172.16.4.4/", "private_address"),
        ("http://192.168.1.1/", "private_address"),
        ("http://100.100.1.2/", "cgnat_address"),
        ("http://[fd00::1]/", "ula_address"),
        ("http://0.0.0.0/", "unspecified_address"),
        ("http://[::]/", "unspecified_address"),
        ("http://224.0.0.1/", "reserved_address"),
    ],
)
def test_refused_urls_have_distinct_reasons(url, reason):
    assert reject(url, resolver=no_dns) == reason
    assert reason in REASONS


def test_named_hosts_are_checked_against_every_resolved_address():
    assert reject("https://www.sec.gov/", resolver=answers(PUBLIC)) is None
    assert reject("https://www.sec.gov/", resolver=answers(PUBLIC, "10.1.2.3")) == "private_address"
    assert reject("https://rebind.example.com/", resolver=answers("127.0.0.1")) == (
        "loopback_address"
    )
    assert reject("https://nowhere.example.com/", resolver=answers()) == "unresolvable_host"
    assert reject("https://www.sec.gov/", resolver=answers("2606:4700::6810:84e5")) is None


def test_public_literal_passes_and_resolution_happens_once(monkeypatch):
    calls = []

    def resolver(host):
        calls.append(host)
        return [PUBLIC]

    assert reject("http://93.184.215.14/x", resolver=no_dns) is None
    assert reject("https://Example.COM./x", resolver=resolver) is None
    assert calls == ["example.com"]


def test_default_resolver_failure_is_unresolvable(monkeypatch):
    def fail(*args, **kwargs):
        raise netguard.socket.gaierror("synthetic")

    monkeypatch.setattr(netguard.socket, "getaddrinfo", fail)
    assert reject("https://nowhere.example.com/") == "unresolvable_host"
