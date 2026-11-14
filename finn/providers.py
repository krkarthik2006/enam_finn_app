import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from engine.financials import parse_screener
from finn.config import Settings
from finn.models import Announcement, Price, PriceImport
from ingest.cache import SourceCache


class ProviderError(Exception):
    pass


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FINNResearch/0.1)",
    "Accept": "application/json,text/html,*/*",
}


def json_list(response, key=None):
    value = response.json()[key] if key else response.json()
    if not isinstance(value, list):
        raise ValueError("Expected a list from source")


def screener_page(response):
    if not BeautifulSoup(response.text, "html.parser").select_one("#quarters, #documents"):
        raise ValueError("Screener returned no company sections")


class Providers:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache = SourceCache(settings.cache_path, settings.offline_sources)

    def client(self):
        return httpx.Client(
            timeout=self.settings.request_timeout_seconds, headers=HEADERS, follow_redirects=False
        )

    def prices(self, ticker, exchange="NSE"):
        suffix = ".NS" if exchange == "NSE" else ".BO"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker + suffix)}"
        try:
            with self.client() as client:
                response = self.cache.fetch(client, url, params={"range": "1y", "interval": "1d"},
                                            validate=lambda r: r.json()["chart"]["result"][0]["timestamp"])
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
            return PriceImport(ticker=ticker, prices=bars[-365:], source=response.extensions.get("finn_source"))
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Yahoo daily prices unavailable or response format changed") from exc

    def announcements(self, ticker, days, bse_code=None):
        if bse_code:
            try:
                return self.bse_announcements(ticker, bse_code, days)
            except ProviderError as exc:
                self.cache.observations.append({
                    "url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
                    "origin": "failed", "stale": False, "failure": str(exc),
                })
        return self._nse_announcements(ticker, days)

    def _nse_announcements(self, ticker, days):
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        try:
            with self.client() as client:
                if not self.settings.offline_sources:
                    # Bootstrap cookies when possible; a blocked homepage must not prevent snapshot fallback.
                    try:
                        client.get("https://www.nseindia.com/", headers={"Accept": "text/html"})
                    except httpx.HTTPError:
                        pass
                response = self.cache.fetch(client,
                    "https://www.nseindia.com/api/corporate-announcements",
                    params={
                        "index": "equities",
                        **({"symbol": ticker} if ticker else {}),
                        "from_date": (now - timedelta(days=days)).strftime("%d-%m-%Y"),
                        "to_date": now.strftime("%d-%m-%Y"),
                    },
                    headers={
                        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
                    },
                    validate=json_list,
                )
                response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ProviderError("NSE returned an unexpected response")
            results = []
            for row in rows:
                if ticker and row.get("symbol", "").upper() != ticker:
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
                        ticker=row.get("symbol", "").upper(),
                        title=row.get("desc") or "Exchange announcement",
                        body=row.get("attchmntText") or "",
                        url=row.get("attchmntFile") or "",
                        published_at=parsed,
                        source=response.extensions.get("finn_source"),
                    )
                )
            return results
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                "NSE announcements unavailable; exchange may be blocking automated requests"
            ) from exc

    def bse_announcements(self, ticker, code, days):
        if not re.fullmatch(r"\d{6}", code):
            raise ProviderError("A verified six-digit BSE scrip code is required")
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        result = []
        try:
            with self.client() as client:
                for page in range(1, 51):
                    response = self.cache.fetch(client,
                        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
                        params={"pageno": page, "strCat": "-1", "strPrevDate": (now-timedelta(days=days)).strftime("%Y%m%d"),
                                "strScrip": code, "strSearch": "P", "strToDate": now.strftime("%Y%m%d"),
                                "strType": "C", "strAnnType": "A", "strSubCat": "-1"},
                        headers={"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"},
                        validate=lambda r: json_list(r, "Table"))
                    data = response.json()
                    rows = data["Table"]
                    for row in rows:
                        if str(row.get("SCRIP_CD")) != code:
                            continue
                        stamp = datetime.fromisoformat(row["NEWS_DT"].replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                        attachment = row.get("ATTACHMENTNAME") or ""
                        result.append(Announcement(
                            ticker=ticker, title=row.get("NEWSSUB") or row.get("HEADLINE") or "BSE filing",
                            body=row.get("HEADLINE") or "", published_at=stamp,
                            url="https://www.bseindia.com/xml-data/corpfiling/AttachLive/" + attachment if attachment else "",
                            source={**response.extensions.get("finn_source", {}),
                                    "exchange_category": row.get("CATEGORYNAME"), "exchange_subcategory": row.get("SUBCATNAME")},
                        ))
                    total = int(data.get("Table1", [{}])[0].get("ROWCNT", len(rows)))
                    if not rows or page * 50 >= total:
                        return result
            raise ProviderError("BSE pagination exceeded limit; narrow the date window")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("BSE filings unavailable or response format changed") from exc

    def fundamentals(self, ticker):
        url = f"https://www.screener.in/company/{quote(ticker)}/consolidated/"
        try:
            with self.client() as client:
                response = self.cache.fetch(client, url, validate=screener_page)
            records = parse_screener(response.text, ticker, url)
            records = [r.model_copy(update={"source": response.extensions.get("finn_source")}) for r in records]
            soup = BeautifulSoup(response.text, "html.parser")
            code = None
            for link in soup.select('a[href*="bseindia.com"]'):
                match = re.search(r"(?:/|=)(\d{6})(?:/|&|$)", link.get("href", ""))
                if match:
                    code = match.group(1)
                    break
            return {"records": records, "bse_code": code, "source": response.extensions.get("finn_source")}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Screener financial tables unavailable or format changed") from exc

    def discover(self, ticker):
        url = f"https://www.screener.in/company/{quote(ticker)}/consolidated/"
        try:
            with self.client() as client:
                response = self.cache.fetch(client, url, validate=screener_page)
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
                        parent = anchor.find_parent("li")
                        links.append(
                            {
                                "kind": kind,
                                "title": parent.get_text(" ", strip=True) if parent else title,
                                "url": link,
                                "download_host_allowed": urlparse(link).hostname
                                in self.settings.document_hosts,
                            }
                        )
            return {
                "ticker": ticker,
                "discovery_url": url,
                "documents": links,
                "company_website": next((a.get("href") for a in soup.select(".company-links a[href]")
                                         if "screener.in" not in (urlparse(a.get("href", "")).hostname or "")
                                         and "bseindia.com" not in (urlparse(a.get("href", "")).hostname or "")
                                         and "nseindia.com" not in (urlparse(a.get("href", "")).hostname or "")), None),
                "source": response.extensions.get("finn_source"),
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
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in self.settings.document_hosts
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("Use an HTTPS URL on FINN_DOCUMENT_HOSTS")
        identifier = hashlib.sha256(url.encode()).hexdigest()
        target = self.settings.cache_path / "pdf" / (identifier + ".pdf")
        metadata = target.with_suffix(".json")
        for attempt in range(2):
            if self.settings.offline_sources:
                break
            try:
                content = self._download(url)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(content)
                temporary.replace(target)
                source = {"url": url, "fetched_at": datetime.now(timezone.utc).isoformat(),
                          "origin": "live", "stale": False}
                metadata.write_text(json.dumps(source))
                self.cache.observations.append(source)
                return content
            except (httpx.HTTPError, ProviderError):
                if attempt:
                    break
        if target.exists() and metadata.exists():
            content = target.read_bytes()
            if not content.startswith(b"%PDF-") or len(content) > 20_000_000:
                raise ValueError("Cached PDF is invalid")
            source = {**json.loads(metadata.read_text()), "origin": "cache", "stale": True}
            self.cache.observations.append(source)
            return content
        raise ProviderError("Document download unavailable and no cached PDF exists")

    def _download(self, url):
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
