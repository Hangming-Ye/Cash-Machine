# Calling the platform

Read-only research API. **Never** places, modifies, or cancels orders.

Programmatic entry: `sec_analysis.SecAnalysisClient`. It composes the existing
market-data / news / fundamentals routers and the IBKR / Longbridge read-only
brokers. The CLI (`sec-analysis`) is the same surface.

---

## 1. Install

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
cp .env.example .env
# Fill secrets locally. Never commit .env.
```

Optional extras (heavy / vendor SDKs):

| Extra | Needed for |
| --- | --- |
| `akshare` | CN quotes, bars, company news, Sina 财报 |
| `longbridge` | Live Longbridge account reads (`LONGBRIDGE_MODE=live`) |
| `ibkr` | Optional later TWS (`ib_insync`). Flex Web Service needs no extra. |
| `yfinance` | Optional options chain only |

```bash
uv sync --extra akshare --group dev
# uv sync --extra longbridge
```

---

## 2. Environment and routing (names only)

Copy `.env.example`. Do not commit values.

**Finnhub (US / HK quotes, general + US company news)**

- `FINNHUB_API_KEY`
- `MARKET_DATA_ROUTE_US`, `MARKET_DATA_ROUTE_HK`, `MARKET_DATA_ROUTE_DEFAULT` (default `finnhub`)
- `NEWS_PROVIDER`, `NEWS_ROUTE_US`, `NEWS_ROUTE_HK`, `NEWS_ROUTE_DEFAULT`

**Tiingo (US daily / EOD OHLCV + volume)**

- `TIINGO_API_KEY` — missing → `ProviderConfigError` (no invented bars)
- `HISTORY_ROUTE_US=tiingo`, `HISTORY_ROUTE_DEFAULT=tiingo` (bare `AAPL` bars)
- Empty `HISTORY_ROUTE_CN` / `HK` falls back to that market's `MARKET_DATA_ROUTE_*`

**FMP (US profile + income / balance / cash)**

- `FMP_API_KEY` — missing → `ProviderConfigError` (no invented figures)
- `FUNDAMENTALS_ROUTE_US=fmp`, `FUNDAMENTALS_ROUTE_DEFAULT=fmp`

**AKShare (CN only)**

- `MARKET_DATA_ROUTE_CN=akshare`
- `NEWS_ROUTE_CN=akshare`
- `FUNDAMENTALS_ROUTE_CN=akshare`
- Extra: `uv sync --extra akshare` (no API key)

**IBKR read-only — Flex Web Service is the phase-1 path (no Gateway)**

Enable Flex Web Service (once per user):

1. Log into IBKR **Client Portal**.
2. **Settings → Reporting → Flex Web Service**.
3. Generate a token. Treat it as a password. Never commit it.
4. Leave the token active. Regenerating invalidates the previous one.

Create an **Activity Flex Query** (one query can cover account + positions + trades):

1. **Performance & Reports → Flex Queries** (or Settings → Reporting → Flex Queries).
2. Create **Activity Flex Query**.
3. Enable delivery via **Flex Web Service** (not email-only).
4. Suggested sections:
   - **Account Information** — account id, name, base currency
   - **Open Positions** — symbol, quantity, mark, cost
   - **Trades** (executions) — trade id, side, qty, price, time
   - **Cash Report** — ending cash / net liquidation (useful for `account`)
5. Format: **XML** (default) or **CSV**. Both are parsed.
6. Period: Last Business Day or a date range. Statements are typically **T+1**.
7. Save and copy the numeric **Query ID**.

Env:

- `BROKER_CLIENT=ibkr`
- `BROKER_IBKR_MODE` — `auto` (default: Flex when token + any query id are set) \| `flex` (require Flex) \| `gateway` (skip Flex; use Gateway stubs)
- `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID`
- Optional split: `IBKR_FLEX_ACTIVITY_QUERY_ID`, `IBKR_FLEX_POSITION_QUERY_ID`
- `IBKR_READONLY` (must stay `true`)
- Gateway stubs only (not required for Flex): `IBKR_GATEWAY_MODE` (`stub` \| `client_portal` \| `tws`), `IBKR_HOST`, `IBKR_PORT`

Flow used by the client: `SendRequest` → poll `GetStatement` until ready (retry 1019 / 1018 / 1001 / 1014) → parse XML or CSV. No Client Portal Gateway. No order placement.

Missing Flex config → `ProviderConfigError`. **No invented USD balances, positions, or fills.** Never commit the token.

CLI (needs a real token locally; CI uses mocks):

```bash
uv run sec-analysis account --broker ibkr
uv run sec-analysis executions --broker ibkr
uv run sec-analysis executions --flex
```

Without token (CI / local smoke): the same commands exit non-zero with Flex setup text.

**Longbridge read-only (no quotes)**

- `LONGBRIDGE_AUTH` — `token` (default, or unset) \| `oauth` (`apikey` is an alias of `token`)
- Token trio (default): `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` (aliases `LONGPORT_*`)
- OAuth: `LONGBRIDGE_CLIENT_ID` only (public client from register curl; **no client secret**)
- `LONGBRIDGE_MODE` (`stub` \| `live`)
- `LONGBRIDGE_ACCOUNT_ID` (optional label)
- **Do not put OAuth access tokens in `.env`.** SDK store: `~/.longbridge/openapi/tokens/<client_id>`
- OAuth login: `sec-analysis longbridge-login` or first `account --broker longbridge` when `AUTH=oauth` and `MODE=live`

Register a public OAuth client (save `client_id` only):

```bash
curl -X POST https://openapi.longbridge.com/oauth2/register \
     -H "Content-Type: application/json" \
     -d '{
            "redirect_uris": ["http://localhost:60355/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code","refresh_token"],
            "response_types": ["code"],
            "client_name": "sec-analysis"
        }'
```

Then:

```bash
# .env: LONGBRIDGE_AUTH=oauth  LONGBRIDGE_CLIENT_ID=...  LONGBRIDGE_MODE=live
uv sync --extra longbridge
uv run sec-analysis longbridge-login
uv run sec-analysis account --broker longbridge
```

Comma lists work like `MARKET_DATA_ROUTE_CN=akshare` (ordered adapters). JP/KR stay stub.

---

## 3. Unified Python API

```python
from sec_analysis import SecAnalysisClient
from sec_analysis.core.errors import ProviderConfigError, ProviderError

client = SecAnalysisClient()  # Settings() / .env
# or: SecAnalysisClient.from_settings(Settings(...))

print(client.routes())  # adapter names; no live HTTP
```

### Quotes and bars

```python
us = client.quote("AAPL", market="US")          # Finnhub
cn = client.quote("600519")                     # AKShare; also 600519.SH / sh600519
hk = client.quote("00700.HK")                   # Finnhub
us_bars = client.bars("AAPL", interval="1d", limit=5)  # Tiingo EOD
bars = client.bars("000001.SZ", interval="1d", limit=5)
```

### News

```python
general = client.news(limit=5)                  # Finnhub general
us_news = client.company_news("AAPL", limit=5)  # Finnhub
cn_news = client.company_news("600519")         # AKShare stock_news_em
cn_news = client.news("600519", market="CN")    # same
# client.news(market="CN")  → ProviderConfigError (needs a symbol)
```

### Fundamentals / CN 财报

```python
snap = client.fundamentals("AAPL")              # FMP profile
us_is = client.statement("AAPL", statement="income")
us_bs = client.statement("AAPL", statement="balance")
us_cf = client.statement("AAPL", statement="cash")
income = client.statement("600519", statement="income")
balance = client.statement("000001.SZ", statement="资产负债表", limit_periods=4)
cash = client.statement("sh600519", statement="cash")
```

`--` / empty Sina cells are omitted. Empty tables raise `ProviderError`.

### Broker read-only

```python
# IBKR / Longbridge without a live session → ProviderConfigError
# (no invented USD / HKD balances)
try:
    ibkr = client.account()                      # Flex when IBKR_FLEX_* set
    ibkr_pos = client.positions()
    session = client.executions()                # Flex Activity trades
    flex = client.executions(flex=True)          # same Flex path, explicit 
    client.longbridge_login()                 # prints authorize URL; token on disk
    lb = client.account(broker="longbridge")
    fills = client.executions(broker="longbridge")
    hist = client.executions(broker="longbridge", history=True)
except ProviderConfigError as exc:
    print(exc)
```

Catch `ProviderConfigError` (missing key / extra / CN news without symbol) and
`ProviderError` (upstream / scrape / parse). Do not substitute zeros.

---

## 4. Equivalent CLI

| Python | CLI |
| --- | --- |
| `client.quote("AAPL", market="US")` | `sec-analysis quote AAPL --market US` |
| `client.bars("AAPL", limit=5)` | `sec-analysis bars AAPL --limit 5` |
| `client.statement("AAPL", statement="income")` | `sec-analysis fundamentals AAPL --statement income` |
| `client.quote("600519")` | `sec-analysis quote 600519` |
| `client.bars("000001.SZ", limit=5)` | `sec-analysis bars 000001.SZ --limit 5` |
| `client.news(limit=5)` | `sec-analysis news --limit 5` |
| `client.company_news("AAPL")` | `sec-analysis company-news AAPL` |
| `client.company_news("600519")` | `sec-analysis company-news 600519` or `news --market CN --symbol 600519` |
| `client.statement("600519", statement="income")` | `sec-analysis fundamentals 600519 --statement income` or `statements 600519 -s income` |
| `client.statement("000001", statement="资产负债表")` | `sec-analysis fundamentals 000001 -s 资产负债表` |
| `client.account()` / `client.positions()` | `sec-analysis account --broker ibkr` (Flex when `IBKR_FLEX_*` set) |
| `client.longbridge_login()` | `sec-analysis longbridge-login` |
| `client.account(broker="longbridge")` | `sec-analysis account --broker longbridge` |
| `client.executions(flex=True)` | `sec-analysis executions --flex` |
| `client.executions(broker="longbridge", history=True)` | `sec-analysis executions --broker longbridge --history` |
| `client.is_connected()` | Shown in the CLI account table (`connected`) |
| `client.routes()` | `sec-analysis providers` |

```bash
uv run sec-analysis quote 600519
uv run sec-analysis bars 000001.SZ --limit 5
uv run sec-analysis company-news 600519
uv run sec-analysis statements 600519 -s 利润表 --periods 4
uv run sec-analysis account --broker ibkr
uv run sec-analysis executions --broker ibkr
uv run sec-analysis executions --flex
uv run sec-analysis longbridge-login
uv run sec-analysis account --broker longbridge
```

---

## 5. Errors

| Situation | What you get |
| --- | --- |
| Missing `FINNHUB_API_KEY` on US/HK quotes or general news | `ProviderConfigError` with setup text |
| Missing `TIINGO_API_KEY` on US / default history | `ProviderConfigError`; **no invented bars** |
| Missing `FMP_API_KEY` on US fundamentals / statements | `ProviderConfigError`; **no invented figures** |
| FMP HTTP 401/403 on `/stable/...` | `ProviderError` (check `FMP_API_KEY` / plan). New keys are stable-only; v3 is not used |
| `akshare` extra missing on a CN route | `ProviderConfigError` (`uv sync --extra akshare`) |
| East Money / Sina scrape break or empty table | Quotes: `bid_ask_em` → `spot_em` → Sina `stock_zh_a_spot` → TX `spot_tx`. Bars: EM hist → `hist_tx`. **No invented last/OHLC** |
| Finnhub `/stock/candle` HTTP 403 | `ProviderError` (free-tier often blocks candles). No invented bars |
| Longbridge OAuth missing `LONGBRIDGE_CLIENT_ID` or `LONGBRIDGE_MODE=stub` | `ProviderConfigError`; **no invented HKD balances**. Run `longbridge-login` |
| IBKR Flex token/query missing | `ProviderConfigError`; **no invented USD balances or fills**. Enable Flex Web Service |
| IBKR `IBKR_READONLY=false` | Settings validation error |
| CN news without a symbol | `ProviderConfigError` |

The library never invents last prices, headlines, statement rows, or balances.

---

## 6. Non-goals

- **No trading.** No place / cancel / modify on the façade, routers, or brokers.
- **No fabricated numbers.** Fail or return empty with a clear error.
- **CN free-tier scrapes are unstable.** **2026-09:** EM bid_ask / spot_em / hist often empty or disconnected. Quote chain: `stock_bid_ask_em` → `stock_zh_a_spot_em` → Sina `stock_zh_a_spot` (`sh`/`sz` codes) → Tencent `stock_zh_a_spot_tx` (`zxj` last only). Bars: EM hist → `hist_tx`. All fail → `ProviderError`; never invent last.
- **No Longbridge quotes.** Phase-1 Longbridge is account / positions / fills only.
- **No BaoStock / Tushare / efinance.**
- Finnhub has **no** options API.

Offline check: `uv run pytest` (injected mocks; no live Tiingo, FMP, East Money, Sina, Finnhub, or Longbridge).
