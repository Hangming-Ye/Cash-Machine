"""IBKR read-only client.

Phase-1 recommended path is **Flex Web Service** (no Client Portal Gateway):
``IBKR_FLEX_TOKEN`` + ``IBKR_FLEX_QUERY_ID``, or ``BROKER_IBKR_MODE=flex``.
``account`` / ``positions`` / ``executions`` read Activity Flex Query XML
(Account Information, Open Positions, Trades, Cash Report). Typical **T+1**.

Gateway / TWS remain optional stubs (``IBKR_GATEWAY_MODE=client_portal|tws``).
They are not required for Flex.

This class is named ``IbkrReadOnlyClient`` on purpose. It must never grow
write/trading endpoints. See ``safety.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sec_analysis.brokers.ibkr.flex import IbkrFlexReadOnlyClient
from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError
from sec_analysis.core.interfaces import BrokerReadOnlyClient
from sec_analysis.core.models import AccountSummary, Execution, Position
from sec_analysis.providers.stub import StubBrokerReadOnlyClient

logger = logging.getLogger(__name__)

# Required for any future TWS / ib_insync connect(). Never flip this.
TWS_READONLY = True

IBKR_NO_CREDS = (
    "IBKR is not connected. Phase-1 recommended path is Flex Web Service "
    "(no Gateway): set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID, or "
    "BROKER_IBKR_MODE=flex. This client does not invent USD balances, "
    "positions, or fills. Optional later: IBKR_GATEWAY_MODE=client_portal|tws."
)


class IbkrReadOnlyClient(BrokerReadOnlyClient):
    """Read-only IBKR façade. Flex Web Service is implemented; Gateway / TWS stay TODO."""

    name = "ibkr"
    TWS_READONLY = TWS_READONLY

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        if self.settings.ibkr_readonly is not True or TWS_READONLY is not True:
            raise ProviderConfigError("IBKR client refuses to start unless read-only is forced")
        self._stub = StubBrokerReadOnlyClient(
            account_id=self.settings.ibkr_account_id or "DU-PENDING"
        )
        self.flex = IbkrFlexReadOnlyClient(self.settings)
        self._connected = False
        if self.settings.ibkr_use_flex() and self.settings.ibkr_flex_configured():
            self._connected = True
            logger.info("IBKR phase-1 path is Flex Web Service (no Gateway)")
        elif self.settings.ibkr_gateway_mode == "stub":
            logger.info("IBKR client in stub mode — account reads raise (no invented balances)")
        else:
            logger.warning(
                "IBKR_GATEWAY_MODE=%s is reserved (not phase-1). Flex is the "
                "recommended read-only path. Gateway stays unimplemented.",
                self.settings.ibkr_gateway_mode,
            )
            self._connected = False

    def connect(self) -> None:
        """Open a read-only session. Flex needs token + query id only."""
        if self.settings.ibkr_use_flex():
            if not self.settings.ibkr_flex_configured():
                raise ProviderConfigError(IBKR_NO_CREDS)
            self._connected = True
            return
        mode = self.settings.ibkr_gateway_mode
        if mode == "stub":
            raise ProviderConfigError(IBKR_NO_CREDS)
        if mode == "client_portal":
            raise ProviderConfigError(
                "TODO: Client Portal Gateway. Start the IBKR Client Portal Gateway, "
                f"authenticate in the browser, then GET https://{self.settings.ibkr_host}:"
                f"{self.settings.ibkr_port}/v1/api/iserver/auth/status. "
                "Only GET account / position / session-trade routes are in scope."
            )
        if mode == "tws":
            raise ProviderConfigError(
                "TODO: TWS read-only API. Install extra 'sec-analysis[ibkr]', enable "
                "TWS Read-Only API, then connect with ib_insync.IB using "
                f"host={self.settings.ibkr_host} port={self.settings.ibkr_port} "
                f"clientId={self.settings.ibkr_client_id} and readonly=True "
                "(mandatory; this framework never opens a write-enabled session). "
                "Allowed: accountSummary, positions, fills. "
                "Long-term history: Flex Activity Query (T+1)."
            )
        raise ProviderConfigError(f"Unknown IBKR_GATEWAY_MODE: {mode}")

    def is_connected(self) -> bool:
        return self._connected

    def get_account_summary(self) -> AccountSummary:
        if self.settings.ibkr_use_flex():
            return self.flex.get_account_summary()
        self._require_live()
        summary = self._stub.get_account_summary()
        extras = dict(summary.extras)
        extras.update(
            {
                "ibkr_mode": self.settings.ibkr_gateway_mode,
                "ibkr_host": self.settings.ibkr_host,
                "ibkr_port": self.settings.ibkr_port,
                "ibkr_readonly": True,
                "flex_configured": self.flex.is_configured(),
                "note": "mocked until Client Portal / TWS read-only is wired",
            }
        )
        return summary.model_copy(
            update={
                "account_id": self.settings.ibkr_account_id or summary.account_id,
                "as_of": datetime.now(tz=UTC),
                "extras": extras,
            }
        )

    def get_positions(self) -> list[Position]:
        if self.settings.ibkr_use_flex():
            return self.flex.get_positions()
        self._require_live()
        return self._stub.get_positions()

    def get_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Execution]:
        """Flex Activity trades when Flex is the IBKR path; else Gateway stub."""
        if self.settings.ibkr_use_flex():
            return self.flex.get_activity_executions(start=start, end=end)
        self._require_live()
        return self._stub.get_executions(start=start, end=end)

    def get_flex_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Execution]:
        """Long-term Activity Flex history. Typical delay T+1."""
        return self.flex.get_activity_executions(start=start, end=end)

    def _require_live(self) -> None:
        if self.settings.ibkr_gateway_mode == "stub" or not self._connected:
            raise ProviderConfigError(IBKR_NO_CREDS)
