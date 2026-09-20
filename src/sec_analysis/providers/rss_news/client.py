"""RSS news adapter via feedparser (no API key)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any

import feedparser

from sec_analysis.core.errors import ProviderError
from sec_analysis.core.interfaces import NewsProvider
from sec_analysis.core.models import NewsItem
from sec_analysis.core.rate_limit import RateLimiter


class RssNewsProvider(NewsProvider):
    name = "rss"

    def __init__(
        self,
        feeds: list[str],
        *,
        parse: Callable[[str], Any] | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        if not feeds:
            raise ProviderError("RSS_FEEDS is empty")
        self.feeds = feeds
        self._parse = parse or feedparser.parse
        self._limiter = limiter or RateLimiter(calls_per_minute=30, min_interval=0.3)

    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        needle = symbol.upper() if symbol else None
        for url in self.feeds:
            self._limiter.wait()
            parsed = self._parse(url)
            entries = getattr(parsed, "entries", None) or parsed.get("entries", [])
            feed_title = _feed_title(parsed, url)
            for entry in entries:
                item = _entry_to_news(entry, feed_title)
                if needle and needle not in _haystack(item):
                    continue
                if start and item.published_at < start:
                    continue
                if end and item.published_at > end:
                    continue
                if needle:
                    item.symbol = needle
                    if needle not in item.related_symbols:
                        item.related_symbols.append(needle)
                items.append(item)
        items.sort(key=lambda n: n.published_at, reverse=True)
        return items[: max(1, limit)]


def _feed_title(parsed: Any, url: str) -> str:
    feed = getattr(parsed, "feed", None) or parsed.get("feed", {})
    if isinstance(feed, dict):
        title = feed.get("title")
    else:
        title = getattr(feed, "title", None)
        if title is None and hasattr(feed, "get"):
            title = feed.get("title")
    return str(title or url)


def _entry_to_news(entry: Any, feed_title: str) -> NewsItem:
    getter = entry.get if hasattr(entry, "get") else lambda k, d=None: getattr(entry, k, d)
    headline = str(getter("title") or "(no title)")
    link = getter("link")
    summary = getter("summary") or getter("description")
    published = _published_at(getter)
    ident_src = str(getter("id") or link or headline)
    ident = hashlib.sha256(ident_src.encode("utf-8")).hexdigest()[:16]
    return NewsItem(
        id=ident,
        headline=headline,
        summary=summary,
        url=link,
        source=feed_title,
        published_at=published,
    )


def _published_at(getter: Callable[..., Any]) -> datetime:
    parsed = getter("published_parsed") or getter("updated_parsed")
    if isinstance(parsed, struct_time):
        return datetime(*parsed[:6], tzinfo=UTC)
    raw = getter("published") or getter("updated")
    if raw:
        try:
            dt = parsedate_to_datetime(str(raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(tz=UTC)


def _haystack(item: NewsItem) -> str:
    return " ".join(filter(None, [item.headline, item.summary, item.url])).upper()
