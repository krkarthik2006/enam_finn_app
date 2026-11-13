import json
from pathlib import Path

from finn.models import Contact

MOCK = Path(__file__).parents[1] / "data/mock"


def seed_network(db):
    data = json.loads((MOCK / "network.json").read_text())
    # Namespaced identifiers avoid collisions between separately configured owners.
    suffix = "" if db.owner_id == "local" else ":" + db.owner_id
    with db.connect() as conn:
        for entry in data["contacts"]:
            entry = dict(entry)
            identifier = entry.pop("id") + suffix
            entry["knows"] = [i + suffix for i in entry.get("knows", [])]
            contact = Contact(**entry)
            conn.execute("INSERT OR IGNORE INTO contacts(id,payload,owner_id) VALUES (?,?,?)",
                         (identifier, contact.model_dump_json(), db.owner_id))
    investor = json.loads((MOCK / "investor.json").read_text())
    investor["id"] = "investor-" + db.owner_id
    investor["knows"] = [i + suffix for i in investor["knows"]]
    if not db.setting(f"investor:{db.owner_id}", None):
        db.set_setting(f"investor:{db.owner_id}", investor)
    return {"contacts": len(data["contacts"]), "notice": data["notice"], "owner_id": db.owner_id}
