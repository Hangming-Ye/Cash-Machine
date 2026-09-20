"""SQLite cache for bars, news, and historical executions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from sec_analysis.core.models import Bar, Execution, NewsItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    interval TEXT NOT NULL,
    source TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timestamp, interval, source)
);

CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY,
    symbol TEXT,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    related_symbols TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL,
    commission REAL,
    currency TEXT NOT NULL
);
"""


class SqliteCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def put_bars(self, bars: Iterable[Bar]) -> int:
        rows = [
            (
                b.symbol,
                b.timestamp.isoformat(),
                b.interval,
                b.source,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
            )
            for b in bars
        ]
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO bars
            (symbol, timestamp, interval, source, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_bars(self, symbol: str, interval: str = "1d") -> list[Bar]:
        cur = self._conn.execute(
            """
            SELECT * FROM bars
            WHERE symbol = ? AND interval = ?
            ORDER BY timestamp
            """,
            (symbol.upper(), interval),
        )
        return [
            Bar(
                symbol=row["symbol"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                interval=row["interval"],
                source=row["source"],
            )
            for row in cur.fetchall()
        ]

    def put_news(self, items: Iterable[NewsItem]) -> int:
        rows = [
            (
                n.id,
                n.symbol,
                n.headline,
                n.summary,
                n.url,
                n.source,
                n.published_at.isoformat(),
                json.dumps(n.related_symbols),
            )
            for n in items
        ]
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO news
            (id, symbol, headline, summary, url, source, published_at, related_symbols)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_news(self, symbol: str | None = None, limit: int = 50) -> list[NewsItem]:
        if symbol:
            cur = self._conn.execute(
                """
                SELECT * FROM news
                WHERE symbol = ? OR related_symbols LIKE ?
                ORDER BY published_at DESC
                LIMIT ?
                """,
                (symbol.upper(), f"%{symbol.upper()}%", limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM news ORDER BY published_at DESC LIMIT ?",
                (limit,),
            )
        return [
            NewsItem(
                id=row["id"],
                symbol=row["symbol"],
                headline=row["headline"],
                summary=row["summary"],
                url=row["url"],
                source=row["source"],
                published_at=datetime.fromisoformat(row["published_at"]),
                related_symbols=json.loads(row["related_symbols"] or "[]"),
            )
            for row in cur.fetchall()
        ]

    def put_executions(self, fills: Iterable[Execution]) -> int:
        rows = [
            (
                e.execution_id,
                e.account_id,
                e.symbol,
                e.side,
                e.quantity,
                e.price,
                e.executed_at.isoformat(),
                e.commission,
                e.currency,
            )
            for e in fills
        ]
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO executions (
                execution_id, account_id, symbol, side, quantity,
                price, executed_at, commission, currency
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_executions(self, account_id: str | None = None) -> list[Execution]:
        if account_id:
            cur = self._conn.execute(
                "SELECT * FROM executions WHERE account_id = ? ORDER BY executed_at",
                (account_id,),
            )
        else:
            cur = self._conn.execute("SELECT * FROM executions ORDER BY executed_at")
        return [
            Execution(
                execution_id=row["execution_id"],
                account_id=row["account_id"],
                symbol=row["symbol"],
                side=row["side"],
                quantity=row["quantity"],
                price=row["price"],
                executed_at=datetime.fromisoformat(row["executed_at"]),
                commission=row["commission"],
                currency=row["currency"],
            )
            for row in cur.fetchall()
        ]
