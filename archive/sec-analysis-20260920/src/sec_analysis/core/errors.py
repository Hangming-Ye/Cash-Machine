"""Framework-level errors."""


class ProviderError(RuntimeError):
    """A provider call failed (HTTP, parse, or missing optional dependency)."""


class ProviderConfigError(ProviderError):
    """Required configuration (API key, extra, etc.) is missing."""


class BrokerReadOnlyError(RuntimeError):
    """Raised when broker code would violate the read-only contract."""
