"""AKShare A-share company news (phase-1 CN news route).

Uses ``akshare.stock_news_em(symbol=...)`` (East Money scrape). Unofficial
and unstable. Failures raise; we never invent headlines.

General / US / HK news stays on Finnhub. This adapter is company news only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.interfaces import NewsProvider
from sec_analysis.core.models import NewsItem
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.akshare_provider.client import (
    UPSTREAM_HINT,
    _load_akshare,
    _records,
    _upstream_message,
    to_akshare_a_share_code,
)

GENERAL_NEWS_HINT = (
    "AKShare stock_news_em is per-stock A-share news only. "
    "Use: sec-analysis company-news 600519  or  "
    "sec-analysis news --market CN --symbol 600519. "
    "General / US news stays on Finnhub: sec-analysis news"
)


def _default_stock_news(code: str) -> Any:
    return _load_akshare().stock_news_em(symbol=code)


class AkshareNewsProvider(NewsProvider):
    """China A-share company news. Inject ``fetch`` in tests."""

    name = "akshare"

    def __init__(
        self,
        *,
        fetch: Callable[[str], Any] | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._fetch = fetch or _default_stock_news
        self._limiter = limiter or RateLimiter(calls_per_minute=20, min_interval=0.5)

    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        if not symbol:
            raise ProviderConfigError(GENERAL_NEWS_HINT)
        return self.get_company_news(symbol, start=start, end=end, limit=limit)

    def get_company_news(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        code = to_akshare_a_share_code(symbol)
        self._limiter.wait()
        try:
            payload = self._fetch(code)
        except ProviderConfigError:
            raise
        except Exception as exc:
            raise ProviderError(_upstream_message("news", code, exc)) from exc
        items = _items_from_news(code, payload)
        if not items:
            raise ProviderError(
                f"AKShare returned no usable headlines for {code}. {UPSTREAM_HINT}"
            )
        filtered: list[NewsItem] = []
        for item in items:
            if start and item.published_at < start:
                continue
            if end and item.published_at > end:
                continue
            filtered.append(item)
        if not filtered:
            raise ProviderError(
                f"AKShare headlines for {code} were all outside the requested window. "
                f"{UPSTREAM_HINT}"
            )
        return filtered[: max(1, limit)]


def _items_from_news(code: str, payload: Any) -> list[NewsItem]:
    items: list[NewsItem] = []
    for index, row in enumerate(_records(payload)):
        headline = _first_text(row, "新闻标题", "标题", "title", "headline")
        if not headline:
            continue
        published = _as_published(
            row.get("发布时间") or row.get("时间") or row.get("datetime") or row.get("date")
        )
        url = _first_text(row, "新闻链接", "链接", "url", "link")
        outlet = _first_text(row, "文章来源", "来源", "source") or "akshare"
        summary = _first_text(row, "新闻内容", "内容", "content", "summary")
        ident = url or f"akshare-{code}-{published.isoformat()}-{index}"
        items.append(
            NewsItem(
                id=ident,
                headline=headline,
                source=outlet,
                published_at=published,
                symbol=code,
                summary=summary,
                url=url,
                related_symbols=[code],
            )
        )
    return items


def _first_text(row: dict[str, Any], *keys: str) -> str | None:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = row[key] if key in row else lowered.get(key.lower())
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in {"--", "nan", "None"}:
            return text
    return None


def _as_published(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, (int, float)) and value > 0:
        # East Money sometimes uses seconds, sometimes ms.
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if value is None or value == "":
        return datetime(1970, 1, 1, tzinfo=UTC)
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC)
    try:
        parsed_d = date.fromisoformat(text[:10])
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)
    return datetime(parsed_d.year, parsed_d.month, parsed_d.day, tzinfo=UTC)
