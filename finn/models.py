import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Mode = Literal["live", "demo"]
Category = Literal[
    "results",
    "M&A",
    "fund_raise",
    "management_change",
    "litigation",
    "insider_trading",
    "earnings_call",
    "investor_meetings",
    "credit_rating",
    "dividend",
    "bonus_split",
    "capex",
    "press_release",
    "postal_ballot",
    "agm_egm",
    "pledging",
    "unclassified",
]
Ticker = Annotated[str, Field(min_length=1, max_length=30)]


def normalize_ticker(value: str) -> str:
    value = value.strip().upper()
    if value.endswith((".NS", ".BO")):
        value = value[:-3]
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9&_-]{0,29}", value):
        raise ValueError("Use an NSE ticker such as RELIANCE or M&M")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Company(Input):
    ticker: Ticker
    name: str = Field(min_length=1, max_length=200)
    sector: str = Field(default="", max_length=100)
    exchange: Literal["NSE", "BSE"] = "NSE"
    _ticker = field_validator("ticker")(normalize_ticker)


class Portfolio(Input):
    companies: list[Company] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique(self):
        if len({c.ticker for c in self.companies}) != len(self.companies):
            raise ValueError("Portfolio contains duplicate tickers")
        return self


class AlertSettings(Input):
    price_change_percent: float = Field(default=5, gt=0, le=100)
    volume_multiple: float = Field(default=2, gt=1, le=100)
    volume_lookback_days: int = Field(default=20, ge=2, le=90)
    material_categories: list[Category] = ["results", "M&A", "management_change", "litigation", "capex"]


class Announcement(Input):
    ticker: Ticker
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=50000)
    url: str = Field(default="", max_length=2000)
    published_at: datetime
    category: Category | None = None
    mode: Mode = "live"
    _ticker = field_validator("ticker")(normalize_ticker)

    @field_validator("published_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError("published_at must include timezone")
        return value.astimezone(timezone.utc)


class Price(Input):
    day: date
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: int = Field(ge=0)


class PriceImport(Input):
    ticker: Ticker
    prices: list[Price] = Field(min_length=1, max_length=365)
    mode: Mode = "live"
    _ticker = field_validator("ticker")(normalize_ticker)


class Document(Input):
    ticker: Ticker
    kind: Literal["annual_report", "transcript", "quarterly_results"]
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(default="", max_length=2000)
    text: str = Field(default="", max_length=2_000_000)
    published_on: date
    mode: Mode = "live"
    _ticker = field_validator("ticker")(normalize_ticker)


class ResearchQuestion(Input):
    ticker: Ticker
    question: str = Field(
        default="Explain the business, financial trajectory, cash quality and management guidance.",
        min_length=5,
        max_length=2000,
    )
    mode: Mode = "live"
    use_model: bool = True
    _ticker = field_validator("ticker")(normalize_ticker)


class Role(Input):
    company: str = Field(min_length=1, max_length=200)
    ticker: str | None = None
    title: str = Field(min_length=1, max_length=200)
    start_year: int = Field(ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)

    @field_validator("ticker")
    @classmethod
    def ticker_value(cls, value):
        return normalize_ticker(value) if value else None

    @model_validator(mode="after")
    def dates(self):
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must follow start_year")
        return self


class Contact(Input):
    name: str = Field(min_length=1, max_length=200)
    roles: list[Role] = Field(default_factory=list, max_length=30)
    expertise: list[str] = Field(default_factory=list, max_length=30)
    education: list[str] = Field(default_factory=list, max_length=20)
    # Only explicit known edges; shared employers are evidence of overlap, not proof of acquaintance.
    knows: list[str] = Field(default_factory=list, max_length=100)
    provenance: Literal["synthetic", "user_provided", "consented_public"] = "synthetic"
    source_url: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=2000)
    last_contacted: date | None = None


class Refresh(Input):
    tickers: list[str] = Field(default_factory=list, max_length=50)
    days: int = Field(default=7, ge=1, le=30)

    @field_validator("tickers")
    @classmethod
    def clean(cls, values):
        return list(dict.fromkeys(normalize_ticker(v) for v in values))
