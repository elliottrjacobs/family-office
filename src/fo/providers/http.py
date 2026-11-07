"""The one HTTP client research and connect calls use, and safe status handling.

Tests set TRANSPORT to an httpx.MockTransport so no call leaves the process.
"""

import httpx

from fo.errors import OfficeError

TRANSPORT = None
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def client(timeout=TIMEOUT) -> httpx.Client:
    """No proxies or netrc from the environment, and redirects only where a caller follows them."""
    return httpx.Client(
        timeout=timeout, follow_redirects=False, trust_env=False, transport=TRANSPORT
    )


def check(response: httpx.Response, invalid=(401, 403)) -> httpx.Response:
    """Turn a provider status into a stable reason; never include the provider's body."""
    if response.status_code in invalid:
        raise OfficeError("invalid_key", "The provider rejected the API key.")
    if response.status_code == 429:
        raise OfficeError("rate_limited", "The provider is rate limiting requests.")
    if response.status_code == 402:
        raise OfficeError("provider_quota", "The provider account has no remaining credits.")
    if response.status_code >= 400:
        raise OfficeError("provider_error", "The provider request failed.")
    return response


def payload(response: httpx.Response):
    try:
        return response.json()
    except ValueError as exc:
        raise OfficeError(
            "provider_error", "The provider returned an unreadable response."
        ) from exc


def call(method: str, url: str, invalid=(401, 403), **kwargs):
    """One JSON request; network failures become provider_unreachable."""
    try:
        with client() as session:
            response = session.request(method, url, **kwargs)
            check(response, invalid)
            return payload(response)
    except httpx.HTTPError as exc:
        raise OfficeError("provider_unreachable", "The provider could not be reached.") from exc
