"""Public-source snapshots. Cached responses retain their original fetch timestamp."""

import base64
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

_screener_lock = threading.Lock()
_last_screener_fetch = 0.0
_sec_lock = threading.Lock()
_last_sec_fetch = 0.0


class SourceCache:
    def __init__(self, root, offline=False):
        self.root, self.offline = root, offline
        self.observations = []

    def fetch(self, client, url, *, params=None, headers=None, validate=None, max_age_seconds=0):
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        path = self.root / (key + ".json")
        if max_age_seconds and path.exists():
            try:
                snapshot = json.loads(path.read_text())
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot['fetched_at'])).total_seconds()
                if 0 <= age < max_age_seconds:
                    response = self.response(snapshot)
                    if validate:
                        validate(response)
                    return self.record(response, snapshot, 'cache', fresh=True)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        failure = "offline mode"
        if not self.offline:
            for attempt in range(2):
                try:
                    if "www.screener.in/" in url:
                        global _last_screener_fetch
                        with _screener_lock:
                            time.sleep(max(0, 1 - (time.monotonic() - _last_screener_fetch)))
                            _last_screener_fetch = time.monotonic()
                    if url.startswith(('https://www.sec.gov/', 'https://data.sec.gov/')):
                        global _last_sec_fetch
                        with _sec_lock:
                            time.sleep(max(0, 0.2 - (time.monotonic() - _last_sec_fetch)))
                            _last_sec_fetch = time.monotonic()
                    response = client.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    if len(response.content) > 20_000_000:
                        raise ValueError("Source exceeds size limit")
                    if validate:
                        validate(response)
                    snapshot = {
                        "url": str(response.url), "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "content_type": response.headers.get("content-type", ""),
                        "body": base64.b64encode(response.content).decode(),
                    }
                    self.root.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                    temporary.write_text(json.dumps(snapshot))
                    temporary.replace(path)
                    return self.record(response, snapshot, "live")
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                    # URLs are public, but do not retain arbitrary provider bodies or headers.
                    failure = type(exc).__name__
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                        if exc.response.status_code != 429:
                            break
                    if not attempt:
                        time.sleep(0.25)
        if not path.exists():
            packaged = Path(__file__).parents[1] / "data/cache/demo_sources" / path.name
            if packaged.exists():
                path = packaged
        if path.exists():
            snapshot = json.loads(path.read_text())
            response = self.response(snapshot)
            if validate:
                validate(response)
            return self.record(response, snapshot, "cache", failure)
        raise httpx.ConnectError(f"Public source unavailable ({failure}); no cached snapshot", request=httpx.Request("GET", url))

    @staticmethod
    def response(snapshot):
        return httpx.Response(200, content=base64.b64decode(snapshot['body']),
                              headers={'content-type': snapshot['content_type']},
                              request=httpx.Request('GET', snapshot['url']))

    def record(self, response, snapshot, origin, failure=None, fresh=False):
        source = {"url": snapshot["url"], "fetched_at": snapshot["fetched_at"], "origin": origin,
                  "stale": origin == "cache" and not fresh, "failure": failure}
        response.extensions["finn_source"] = source
        self.observations.append(source)
        return response
