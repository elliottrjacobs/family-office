import httpx

from fo.config import read_config, read_secrets
from fo.errors import OfficeError
from fo.providers.cache import Cache


def fetch_json(url, params=None, headers=None):
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OfficeError(
            "provider_error", "Market data request failed; request credentials are hidden."
        ) from exc


class Market:
    def __init__(self, root, read_only=False):
        self.root = root
        self.config = read_config(root)
        self.keys = {} if read_only else read_secrets(root)
        self.cache = Cache(root, read_only)

    def alpha(self, function, symbol):
        settings = self.keys.get("alphavantage", {})
        key = settings.get("api_key")
        fetch = (
            (
                lambda: fetch_json(
                    "https://www.alphavantage.co/query",
                    {"function": function, "symbol": symbol, "apikey": key},
                )
            )
            if key
            else None
        )
        return self.cache.get(
            f"alpha:{function}:{symbol}",
            900 if function == "GLOBAL_QUOTE" else 86400,
            fetch,
            "alphavantage",
            self.config.get("providers", {}).get("alphavantage", {}).get("daily_limit", 25),
        )

    def quote(self, symbol):
        from fo.providers.schwab import Schwab

        try:
            client = Schwab(self.root) if self.keys.get("schwab") else None
            return self.cache.get(
                "schwab:quote:" + symbol, 900, (lambda: client.quote([symbol])) if client else None
            )
        except OfficeError:
            return self.alpha("GLOBAL_QUOTE", symbol)

    def edgar(self, path):
        if path.startswith("/") or ".." in path or "?" in path:
            raise OfficeError("invalid_query", "Invalid EDGAR resource path.")
        agent = self.config.get("providers", {}).get("edgar", {}).get("user_agent")
        fetch = (
            (lambda: fetch_json("https://data.sec.gov/" + path, headers={"User-Agent": agent}))
            if agent
            else None
        )
        return self.cache.get("edgar:" + path, 86400, fetch)

    def frames(self, concept, period, unit="USD"):
        return self.edgar(f"api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json")

    def series(self, name):
        key = self.keys.get("fred", {}).get("api_key")
        fetch = (
            (
                lambda: fetch_json(
                    "https://api.stlouisfed.org/fred/series/observations",
                    {"series_id": name, "api_key": key, "file_type": "json"},
                )
            )
            if key
            else None
        )
        return self.cache.get("fred:" + name, 86400, fetch)
