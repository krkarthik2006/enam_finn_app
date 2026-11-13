"""Read-only check of upstream connectors. Does not call GLM or change the database."""

import json
import sys

from finn.config import Settings
from finn.models import normalize_ticker
from finn.providers import Providers

symbol = normalize_ticker(sys.argv[1] if len(sys.argv) > 1 else "TCS")
providers = Providers(Settings(request_timeout_seconds=15))
for name, fetch in [
    ("prices", lambda: len(providers.prices(symbol).prices)),
    ("announcements", lambda: len(providers.announcements(symbol, 7))),
    ("document_discovery", lambda: len(providers.discover(symbol)["documents"])),
]:
    try:
        print(json.dumps({"source": name, "status": "ok", "records": fetch()}), flush=True)
    except Exception as exc:
        print(json.dumps({"source": name, "status": "error", "message": str(exc)}), flush=True)
