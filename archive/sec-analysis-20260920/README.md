# 证券分析工程框架 / Securities Analysis Framework

只读研究脚手架。本仓库**不会、也不得**下单、改单或撤单。

Read-only research scaffolding. **Never** places, modifies, or cancels orders.

**How to call the platform:** [docs/calling-guide.md](docs/calling-guide.md) — `SecAnalysisClient` (Python) and `sec-analysis` (CLI).

## Phase-1 scope (locked)

Implemented and prioritized **only**:

1. **Finnhub** — US / HK quotes + general / US company news (not US historical bars)
2. **Tiingo** — US daily / EOD OHLCV + volume (`HISTORY_ROUTE_US=tiingo`)
3. **FMP** — US profile snapshot + income / balance / cash statements
4. **AKShare** — China A-share spot, daily bars / volume, **company news**, **财报** (Sina three statements)
5. **IBKR read-only** — **Flex Web Service** (phase-1 recommended; no Gateway): account, positions, executions (typical T+1). Gateway / TWS remain optional stubs.
6. **Longbridge read-only** — HK account, stock/fund positions, today + history fills. **No quotes.**

Do not treat Massive, yfinance, EODHD, Twelve Data, BaoStock, Tushare, or efinance as US primary.

**Routing:** US / HK quotes → Finnhub. US daily bars → Tiingo. US statements → FMP. CN A-shares → AKShare. CN company news → `stock_news_em`. CN 财报 → `stock_financial_report_sina`. JP / KR → stub.

---

## 中文（阶段一）

### 运行

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --group dev
# A 股行情 / 新闻（较重，默认不装）
uv sync --extra akshare
# 长桥只读账户（有密钥后再装）
# uv sync --extra longbridge
cp .env.example .env
# 填入 FINNHUB_API_KEY（美股 / 港股报价与新闻）
# 填入 TIINGO_API_KEY（美股日 K）与 FMP_API_KEY（美股三张表）
uv run sec-analysis quote AAPL
uv run sec-analysis bars AAPL --limit 5
uv run sec-analysis fundamentals AAPL --statement income
uv run sec-analysis quote 600519
uv run sec-analysis bars 000001.SZ --limit 5
uv run sec-analysis news
uv run sec-analysis company-news AAPL
uv run sec-analysis company-news 600519
uv run sec-analysis news --market CN --symbol 600519
uv run sec-analysis fundamentals 600519 --statement income
uv run sec-analysis statements 600519 --statement income
uv run sec-analysis fundamentals 000001.SZ -s 资产负债表
uv run sec-analysis account --broker ibkr      # Flex 未配 → 配置错误，不编造美元
uv run sec-analysis executions --broker ibkr
uv run sec-analysis executions --flex
uv run sec-analysis account --broker longbridge
uv run pytest
```

没有 `FINNHUB_API_KEY` 时，美股 / 港股报价与新闻会给出**明确错误**，不会悄悄改用 stub。没有 `TIINGO_API_KEY` / `FMP_API_KEY` 时，美股日 K / 财报同样给出**配置错误**，**不会编造 K 线或报表数字**。

AKShare 未安装、东财 / 新浪被限流或页面改版时，A 股行情、新闻、财报同样给出**明确错误**，**不会编造价格、标题或数字**。

### A 股代码、新闻与财报

行情与新闻归一成 **6 位数字**；财报再加成新浪要的 **`sh` / `sz` 前缀**：`600519` → `sh600519`，`000001` → `sz000001`。`.SH` / `.SZ` / `sh600519` 均可。

| 命令 | 源 |
| --- | --- |
| `sec-analysis company-news 600519` | AKShare `stock_news_em(symbol="600519")` |
| `sec-analysis news --market CN --symbol 600519` | 同上 |
| `sec-analysis news` | Finnhub 综合新闻（**不是** A 股） |
| `sec-analysis company-news AAPL` | Finnhub `/company-news` |
| `sec-analysis fundamentals 600519 --statement income` | `stock_financial_report_sina(stock="sh600519", symbol="利润表")` |
| `sec-analysis statements 600519 -s cash` | Same path (quote/news-style command) |
| `sec-analysis fundamentals 000001 -s 资产负债表` | 同上，`sz000001` / 资产负债表 |
| `sec-analysis fundamentals 600519 -s cash` | 现金流量表 |

`--statement` 可用 `income|balance|cash` 或 `利润表|资产负债表|现金流量表`。省略时 A 股默认利润表。美股 `fundamentals AAPL --statement income|balance|cash` 走 FMP 三张年报；省略 `--statement` 时是 FMP profile 快照。

未接 `stock_financial_abstract`（另一套表，多一次爬取）。北交所 `bj` 代码会明确拒绝。

AKShare 爬东方财富 / 新浪，**非正式、不稳定**。失败就失败，绝不填假数。CI 用 mock，不访问东财或新浪。

**2026-09 实测：** 东财 `stock_bid_ask_em` 空 JSON、`stock_zh_a_spot_em` / `stock_zh_a_hist` 断连。现价再走新浪 `stock_zh_a_spot`（`sh600519`）或腾讯 `stock_zh_a_spot_tx`；日 K 回退 `stock_zh_a_hist_tx`。全部失败才报错，**不编造 last**。

### 经纪商只读

- **IBKR**（阶段一只读，推荐 **Flex Web Service**，不需要 Client Portal Gateway）：
  1. Client Portal → Settings → Reporting → **Flex Web Service** → 生成 token（当密码保管，勿提交）
  2. 新建 **Activity Flex Query**，勾选 **Flex Web Service** 投递（不要只走邮件）。建议段：Account Information、Open Positions、Trades（成交）、Cash Report。格式 XML（默认）或 CSV。记下 Query ID
  3. 本地 `.env`：`IBKR_FLEX_TOKEN`、`IBKR_FLEX_QUERY_ID`。`BROKER_IBKR_MODE=auto`（有 token+query 就走 Flex）或 `flex`
  4. `uv run sec-analysis account --broker ibkr` / `executions --broker ibkr` / `executions --flex`（一般为 **T+1**）
  - `IBKR_READONLY` 不能关。Gateway/TWS 仍是可选 stub（`IBKR_GATEWAY_MODE=client_portal|tws`），不是阶段一主路径。未配 Flex 给出**明确配置错误**，**不会编造美元余额**。
- **长桥**（只读）：默认仍是 **token 三件套**（`LONGBRIDGE_AUTH=token` 或未设）：`LONGBRIDGE_APP_KEY` / `_APP_SECRET` / `_ACCESS_TOKEN`（`LONGPORT_*` 仍可用）。
  - **可选 OAuth 2.0**（`LONGBRIDGE_AUTH=oauth`）。不要把 OAuth access token 写进 `.env`。
    1. 注册客户端（只保存 `client_id`；公开客户端，无需 secret）：
       ```bash
       curl -X POST https://openapi.longbridge.com/oauth2/register \
            -H "Content-Type: application/json" \
            -d '{"redirect_uris":["http://localhost:60355/callback"],"token_endpoint_auth_method":"none","grant_types":["authorization_code","refresh_token"],"response_types":["code"],"client_name":"sec-analysis"}'
       ```
    2. 本地 `.env`：`LONGBRIDGE_AUTH=oauth`、`LONGBRIDGE_CLIENT_ID=...`、`LONGBRIDGE_MODE=live`
    3. `uv sync --extra longbridge` 后 `uv run sec-analysis longbridge-login`（打印授权 URL；SDK 把 token 写到 `~/.longbridge/openapi/tokens/<client_id>`）
    4. 之后：`sec-analysis account --broker longbridge`（无缓存时同样打印授权 URL）
  - 未登录给出**明确配置错误**，**不会编造余额**。阶段一**不用**长桥行情。代码扫描禁止下单类方法。

### 配置

见 `.env.example`。Finnhub **没有** options API。

---

## English technical notes

| Command | Behavior |
| --- | --- |
| `sec-analysis quote AAPL` | Finnhub `/quote` |
| `sec-analysis bars AAPL` | Tiingo `/tiingo/daily/AAPL/prices` (needs `TIINGO_API_KEY`) |
| `sec-analysis fundamentals AAPL --statement income` | FMP `/stable/income-statement?symbol=AAPL` (needs `FMP_API_KEY`) |
| `sec-analysis quote 600519` | AKShare `stock_bid_ask_em` |
| `sec-analysis bars 000001.SZ` | AKShare `stock_zh_a_hist(..., period="daily", adjust="")` |
| `sec-analysis news` | Finnhub `/news?category=general` |
| `sec-analysis company-news AAPL` | Finnhub `/company-news` |
| `sec-analysis company-news 600519` | AKShare `stock_news_em` |
| `sec-analysis news --market CN --symbol 600519` | Same as company-news for A-shares |
| `sec-analysis fundamentals 600519 --statement income` | AKShare `stock_financial_report_sina` 利润表 |
| `sec-analysis fundamentals 000001 -s balance` | Sina 资产负债表 (`sz000001`) |
| `sec-analysis account --broker ibkr` | Flex Web Service (`SendRequest` → `GetStatement`) when `IBKR_FLEX_*` set or `BROKER_IBKR_MODE=flex`; else config error (no invented USD) |
| `sec-analysis executions --broker ibkr` | Flex Activity trades (typical T+1) |
| `sec-analysis executions --flex` | Same Flex path, explicit |
| `sec-analysis longbridge-login` | OAuth 2.0: print authorize URL; token on disk, not `.env` |
| `sec-analysis account --broker longbridge` | Longbridge read-only; stub/missing OAuth → config error (no fake balances) |
| `sec-analysis executions --broker longbridge --history` | Longbridge `history_executions` |

### AKShare functions

| Need | Function |
| --- | --- |
| Spot | `stock_bid_ask_em` (retried) → `stock_zh_a_spot_em` filter → Sina `stock_zh_a_spot` (`sh600519`/`sz000001`) → Tencent `stock_zh_a_spot_tx` (`zxj`) |
| Daily bars + volume | `stock_zh_a_hist` (retried); fallback `stock_zh_a_hist_tx(symbol="sh600519"\|"sz000001")` — Tencent OHLCV when East Money hist is down |
| A-share company news | `akshare.stock_news_em(symbol=code)` |
| A-share 财报 (income/balance/cash) | `akshare.stock_financial_report_sina(stock="sh600519"\|"sz000001", symbol="利润表"\|"资产负债表"\|"现金流量表")` |

No BaoStock / Tushare / paid news.

### Longbridge read-only methods

| Need | SDK |
| --- | --- |
| Balances | `TradeContext.account_balance()` |
| Stock positions | `TradeContext.stock_positions()` |
| Fund positions (best-effort) | `TradeContext.fund_positions()` |
| Today fills | `TradeContext.today_executions()` |
| History fills | `TradeContext.history_executions(start_at=..., end_at=...)` |

Optional extra: `uv sync --extra longbridge` (`longbridge>=4.0`). Default: `Config.from_apikey(...)` (`LONGBRIDGE_AUTH=token` or unset). Opt-in OAuth: `OAuthBuilder(client_id).build(...)` then `Config.from_oauth(oauth)` (`LONGBRIDGE_AUTH=oauth`, `LONGBRIDGE_CLIENT_ID`).

Tests mock vendors (`tests/test_tiingo.py`, `tests/test_fmp_rss_yfinance.py`, `tests/test_akshare*.py`, `tests/test_longbridge.py`, `tests/test_flex.py`). **No live Tiingo, FMP, East Money, Sina, Longbridge, or IBKR Flex HTTP in CI.**

```bash
uv run pytest
```

### Live smoke-test (optional)

```bash
uv sync --extra akshare --group dev
uv run sec-analysis providers
# US (needs TIINGO_API_KEY / FMP_API_KEY / FINNHUB_API_KEY in local .env):
uv run sec-analysis quote AAPL --market US
uv run sec-analysis bars AAPL --limit 5
uv run sec-analysis fundamentals AAPL --statement income --periods 4
uv run sec-analysis fundamentals AAPL --statement balance --periods 2
uv run sec-analysis fundamentals AAPL --statement cash --periods 2
uv run sec-analysis quote 600519
uv run sec-analysis company-news 600519 --limit 3
uv run sec-analysis news --market CN --symbol 600519 --limit 3
uv run sec-analysis fundamentals 600519 --statement income --periods 4
uv run sec-analysis fundamentals 000001.SZ -s 现金流量表 --periods 4
# Without Flex token this prints a config error (no fake USD balances):
uv run sec-analysis account --broker ibkr
uv run sec-analysis executions --broker ibkr
uv run sec-analysis executions --flex
# Without Longbridge OAuth this prints a config error (no fake HKD balances):
uv run sec-analysis account --broker longbridge
```

After you register an OAuth client and put `LONGBRIDGE_CLIENT_ID` in a **local** `.env` (never commit tokens):

```bash
uv sync --extra longbridge
# LONGBRIDGE_MODE=live LONGBRIDGE_AUTH=oauth LONGBRIDGE_CLIENT_ID=...
uv run sec-analysis longbridge-login
uv run sec-analysis account --broker longbridge
uv run sec-analysis executions --broker longbridge --history
```

East Money or Longbridge errors exit non-zero. Retry later; do not cache a fabricated headline or balance.
