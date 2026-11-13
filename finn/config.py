from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINN_", env_file=".env", extra="ignore")

    database_path: Path = Path("data/finn.sqlite3")
    glm_api_key: SecretStr = SecretStr("")
    glm_base_url: str = "https://inference.hyde.tech/v1"
    glm_model: str = "hyde/glm-5.3-flash"
    api_token: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    document_hosts: list[str] = [
        "nsearchives.nseindia.com",
        "archives.nseindia.com",
        "www.bseindia.com",
        "www.screener.in",
        "www.ril.com",
        "www.infosys.com",
    ]
    refresh_interval_seconds: int = Field(default=0, ge=0)
    request_timeout_seconds: float = Field(default=30, gt=0, le=120)
