"""Start the single-investor hosted review on a Railway persistent volume."""
import os
from pathlib import Path

import uvicorn

from deploy.bootstrap import bootstrap
from finn.config import Settings
from finn.db import Database
from finn.review import seed_review


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
    if not db.setting("hosted_review_seed", False):
        if db.one("SELECT COUNT(*) n FROM portfolio")["n"] or db.one("SELECT COUNT(*) n FROM contacts")["n"]:
            raise ValueError("Automatic review seeding requires an empty database")
        seed_review(db)
        db.set_setting("hosted_review_seed", True)
    bootstrap(db)
    return db


def main():
    settings = Settings()
    prepare(settings, os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"))
    uvicorn.run("finn.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), workers=1)


if __name__ == "__main__":
    main()
