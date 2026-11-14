"""Response contracts shared with web/lib/types.ts."""
from typing import Any

from pydantic import BaseModel


class SystemStatus(BaseModel):
    status: str
    model: dict[str, Any]
    authentication_enabled: bool
    counts: dict[str, dict[str, int]]
    demo_as_of: str | None
    documents: list[dict[str, Any]]
    refresh_runs: list[dict[str, Any]]
    integrations: list[dict[str, str]]
