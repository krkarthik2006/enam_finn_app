"""Run the review in its own database: .venv/bin/python scripts/run_review.py."""
import os
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.bootstrap import bootstrap
from finn.config import Settings  # noqa: E402
from finn.db import Database  # noqa: E402
from finn.mock_network import seed_network  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    settings = Settings(database_path=root / "data/primary_review.sqlite")
    db = Database(settings.database_path, settings.owner_id)
    db.initialize()
    bootstrap(db)
    seed_network(db)
    env = {**os.environ, "FINN_DATABASE_PATH": str(settings.database_path)}
    web_env = {**env, "FINN_BACKEND_URL": "http://127.0.0.1:8000", "FINN_API_TOKEN": settings.api_token.get_secret_value()}
    web_env.pop("FINN_GLM_API_KEY", None)
    processes = []
    def stop(*_):
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "finn.main:app", "--host", "127.0.0.1", "--port", "8000"], env=env))
        processes.append(subprocess.Popen(["npm", "run", "start" if "--production" in sys.argv else "dev"], cwd=root / "web", env=web_env))
        print("FINN review: http://127.0.0.1:3000 — isolated data/primary_review.sqlite; Ctrl+C stops both servers.", flush=True)
        processes[-1].wait()
    finally:
        stop()


if __name__ == "__main__":
    main()
