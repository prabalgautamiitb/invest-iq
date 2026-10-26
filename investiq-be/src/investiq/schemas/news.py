from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl


class NewsArticle(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=500)
    url: HttpUrl
    source: str
    published_at: AwareDatetime


class MarketNewsOut(BaseModel):
    items: list[NewsArticle] = Field(default_factory=list, max_length=5)
    updated_at: AwareDatetime | None = None
    next_refresh_at: datetime | None = None
    status: Literal["ready", "stale", "unavailable", "disabled"] = "unavailable"
    schedule: str = "Hourly during NSE market hours · 9:15 AM–3:15 PM IST"
