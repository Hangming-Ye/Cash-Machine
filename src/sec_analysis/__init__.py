"""Read-only securities analysis framework.

This package never places, modifies, or cancels broker orders.
Programmatic entry: ``SecAnalysisClient``.
"""

from sec_analysis.client import SecAnalysisClient
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Instrument, Market
from sec_analysis.core.interfaces import (
    BrokerReadOnlyClient,
    FlexActivityReadOnlyClient,
    FundamentalsProvider,
    MarketDataProvider,
    NewsProvider,
    OptionsProvider,
)
from sec_analysis.core.models import (
    AccountSummary,
    Bar,
    Execution,
    Fundamental,
    NewsItem,
    OptionChain,
    OptionContract,
    Position,
    Quote,
    StatementKind,
    StatementLine,
    StatementReport,
)

__version__ = "0.1.0"

__all__ = [
    "SecAnalysisClient",
    "ProviderConfigError",
    "ProviderError",
    "AccountSummary",
    "Bar",
    "BrokerReadOnlyClient",
    "FlexActivityReadOnlyClient",
    "Execution",
    "Fundamental",
    "FundamentalsProvider",
    "Instrument",
    "Market",
    "MarketDataProvider",
    "NewsItem",
    "NewsProvider",
    "OptionChain",
    "OptionContract",
    "OptionsProvider",
    "Position",
    "Quote",
    "StatementKind",
    "StatementLine",
    "StatementReport",
    "__version__",
]
