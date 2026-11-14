"""Start the single-investor hosted review on a Railway persistent volume."""
import os
from pathlib import Path

import uvicorn

from deploy.bootstrap import bootstrap
from finn.config import Settings
from finn.db import Database
from finn.mock_network import seed_network


def prepare(settings, volume):
    if len(settings.api_token.get_secret_value()) < 32:
        raise ValueError("Set a server API token of at least 32 characters before hosting the API")
    if not volume:
        raise ValueError("Attach a persistent volume; ephemeral database deployment is refused")
    mount = Path(volume).resolve()
    if not settings.database_path.resolve().is_relative_to(mount):
        raise ValueError("Database must be stored inside the mounted persistent volume")
    if not settings.cache_path.resolve().is_relative_to(mount):
        raise ValueError("Source cache must be stored inside the mounted persistent volume")
    db = Database(settings.database_path, settings.owner_id)
    db.initialize()
    seed_network(db)
    bootstrap(db)
    if not db.setting("primary_sources_only_v1", False):
        with db.connect() as conn:
            conn.execute("DELETE FROM chunk_search WHERE id IN (SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.mode='demo')")
            conn.execute("DELETE FROM enrichments WHERE event_id IN (SELECT id FROM announcements WHERE mode='demo')")
            for table in ("documents", "announcements", "financials", "prices"):
                conn.execute(f"DELETE FROM {table} WHERE mode='demo'")
            conn.execute("DELETE FROM portfolio WHERE ticker LIKE 'MOCK%'")
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('primary_sources_only_v1', 'true')")
    return db


def main():
    settings = Settings()
    prepare(settings, os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"))
    uvicorn.run("finn.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), workers=1)


if __name__ == "__main__":
    main()
