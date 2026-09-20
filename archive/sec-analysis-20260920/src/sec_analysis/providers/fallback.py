"""Small composition helpers so missing keys still yield a working CLI."""

from __future__ import annotations

import logging
from datetime import datetime

from sec_analysis.core.interfaces import NewsProvider
from sec_analysis.core.models import NewsItem

logger = logging.getLogger(__name__)


class FallbackNewsProvider(NewsProvider):
    """Try ``primary``, then ``fallback`` (used for Finnhub → RSS → stub)."""

    def __init__(
        self,
        primary: NewsProvider,
        fallback: NewsProvider,
        *,
        name: str,
    ) -> None:
        self.name = name
        self._primary = primary
        self._fallback = fallback

    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        try:
            items = self._primary.get_news(symbol, start=start, end=end, limit=limit)
            if items:
                self.name = self._primary.name
                return items
        except Exception as exc:
            logger.warning("Primary news provider %s failed: %s", self._primary.name, exc)
        items = self._fallback.get_news(symbol, start=start, end=end, limit=limit)
        self.name = self._fallback.name
        return items
