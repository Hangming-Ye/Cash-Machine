"""Read-only source adapters for the approved provider baseline."""

from cash_research.sources.finnhub import FinnhubAdapter
from cash_research.sources.tiingo import TiingoAdapter

__all__ = ["FinnhubAdapter", "TiingoAdapter"]
