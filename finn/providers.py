import ipaddress
import socket
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from finn.config import Settings
from finn.models import Announcement, Price, PriceImport


class ProviderError(Exception):
    pass


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FINNResearch/0.1)",
    "Accept": "application/json,text/html,*/*",
}


class Providers:
    def __init__(self, settings: Settings):
        self.settings = settings

    def client(self):
        return httpx.Client(
            timeout=self.settings.request_timeout_seconds, headers=HEADERS, follow_redirects=False
        )

    def prices(self, ticker, exchange="NSE"):
        suffix = ".NS" if exchange == "NSE" else ".BO"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker + suffix)}"
        try:
            with self.client() as client:
                response = client.get(url, params={"range": "6mo", "interval": "1d"})
                response.raise_for_status()
            result = response.json()["chart"]["result"][0]
            quote_data = result["indicators"]["quote"][0]
            today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            bars = []
            for ts, close, volume in zip(
                result["timestamp"], quote_data["close"], quote_data["volume"], strict=True
            ):
                day = datetime.fromtimestamp(ts, ZoneInfo("Asia/Kolkata")).date()
                # Never treat today's still-changing quote as an EOD observation.
                if day >= today or close is None or volume is None:
                    continue
                bars.append(Price(day=day, close=close, volume=volume))
            if not bars:
                raise ProviderError("Yahoo returned no completed daily bars")
            return PriceImport(ticker=ticker, prices=bars)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Yahoo daily prices unavailable or response format changed") from exc

    def announcements(self, ticker, days):
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        try:
            with self.client() as client:
                client.get("https://www.nseindia.com/", headers={"Accept": "text/html"}).raise_for_status()
                response = client.get(
                    "https://www.nseindia.com/api/corporate-announcements",
                    params={
                        "index": "equities",
                        "symbol": ticker,
                        "from_date": (now - timedelta(days=days)).strftime("%d-%m-%Y"),
                        "to_date": now.strftime("%d-%m-%Y"),
                    },
                    headers={
                        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
                    },
                )
                response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ProviderError("NSE returned an unexpected response")
            results = []
            for row in rows:
                if row.get("symbol", "").upper() != ticker:
                    continue
                raw_date = row.get("an_dt") or row.get("sort_date")
                parsed = None
                for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        parsed = datetime.strptime(raw_date, fmt).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                        break
                    except (ValueError, TypeError):
                        continue
                if not parsed:
                    raise ProviderError("NSE announcement timestamp format changed")
                results.append(
                    Announcement(
                        ticker=ticker,
                        title=row.get("desc") or "Exchange announcement",
                        body=row.get("attchmntText") or "",
                        url=row.get("attchmntFile") or "",
                        published_at=parsed,
                    )
                )
            return results
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                "NSE announcements unavailable; exchange may be blocking automated requests"
            ) from exc

    def discover(self, ticker):
        url = f"https://www.screener.in/company/{quote(ticker)}/consolidated/"
        try:
            with self.client() as client:
                response = client.get(url)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            docs = soup.select_one("#documents")
            if docs is None:
                raise ProviderError("No documents section found for this ticker")
            links = []
            for section in docs.select(".documents"):
                heading = section.find(["h2", "h3"])
                label = heading.get_text(" ", strip=True).lower() if heading else ""
                kind = "annual_report" if "annual" in label else "transcript" if "concall" in label else None
                if not kind:
                    continue
                for anchor in section.select("a[href]"):
                    title = anchor.get_text(" ", strip=True)
                    if kind == "transcript" and "transcript" not in title.lower():
                        continue
                    link = urljoin(url, anchor["href"])
                    if urlparse(link).scheme == "https":
                        links.append(
                            {
                                "kind": kind,
                                "title": title,
                                "url": link,
                                "download_host_allowed": urlparse(link).hostname
                                in self.settings.document_hosts,
                            }
                        )
            return {
                "ticker": ticker,
                "discovery_url": url,
                "documents": links,
                "note": "Discovery only. Ingest the selected original document, with its publication date.",
            }
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "Document discovery unavailable; supply an official source URL or source text"
            ) from exc

    def validate_document_url(self, url):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.settings.document_hosts
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Use an HTTPS URL on FINN_DOCUMENT_HOSTS (exact official host required)")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ProviderError("Document host could not be resolved") from exc
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Document URLs must resolve only to public addresses")

    def download(self, url):
        # Each redirect is checked; no credentials are attached to document requests.
        with self.client() as client:
            for _ in range(4):
                self.validate_document_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    content = bytearray()
                    for part in response.iter_bytes():
                        content.extend(part)
                        if len(content) > 20_000_000:
                            raise ValueError("Document exceeds 20 MB download limit")
                    if not content.startswith(b"%PDF-"):
                        raise ValueError(
                            "URL must return a PDF; paste extracted primary-source text for HTML sources"
                        )
                    return bytes(content)
        raise ProviderError("Too many document redirects")
