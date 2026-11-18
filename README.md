# TradingView FX Strategy & Alert Automation

Automated FX intelligence for the 7 major pairs (EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, NZD/USD):

- **Pine Script trend-following breakout strategy** — loaded manually into TradingView, with `alert()` webhooks that post Slack-ready messages.
- **Daily FX report + alpha alerts** — a scheduled Python pipeline (GitHub Actions) that publishes a daily report and qualifying breakout/alpha alerts to Slack, and archives daily CSV snapshots.

> **Disclaimer:** All signals and reports are informational research output only — not trading advice, and not a guarantee of returns. This repo never places orders or routes to a broker.

## Layout

```
pipelines/    Daily FX report + alert pipeline (Python)
strategies/   Pine Script strategies for TradingView
data/fx/      Daily CSV archive (one file per session)
tests/        Unit tests (pytest)
```

## Loading the strategy into TradingView

Source: `strategies/fx_major_breakout.pine` (Pine Script v6). TradingView has no
API for installing strategies, so this is a one-time manual paste per chart.

1. Open a major-pair chart in TradingView (e.g. `EURUSD`, daily timeframe).
2. Open the **Pine Editor** panel (bottom of the chart), delete the placeholder code.
3. Paste the full contents of `strategies/fx_major_breakout.pine`.
4. Click **Save**, then **Add to chart**. The Donchian bands and a red trailing-stop
   line appear on the chart.
5. Verify the **Strategy Tester** tab shows trades on the major pair. If it is empty,
   extend the chart history (the 55-day Donchian short side needs data before the
   first signal) and confirm ADX is above the 20 threshold on entry bars.
6. Create the Slack alert: click the **Alerts** panel → **Create Alert** → set
   **Condition** to `FX Major Breakout` and choose **`alert() function calls only`**
   (not "Order fills only" — the JSON message is emitted by `alert()` calls).
   Recommended: trigger "Once Per Bar Close".
7. Under **Notifications**, check **Webhook URL** and paste your Slack incoming-webhook
   URL as the destination. The message is sent as-is:
   `{"text":"FX breakout: EURUSD long @ 1.0842 (20d Donchian, ADX 27)"}` — Slack
   posts it straight into the channel. No receiver server is needed.

Notes:

- The alert price is the signal bar's close; the strategy order itself fills on the
  next bar's open.
- Sizing is risk-percent-of-equity (default 1%) mapped through the ATR stop distance.
  It is exact for USD-quoted pairs and approximate for USD-base pairs (USDJPY,
  USDCHF, USDCAD).
- Repeat steps 2–7 on one chart per pair you want monitored.

> **Disclaimer:** All signals are informational research output only — not trading
> advice and not a guarantee of returns. This script never places orders.

## Slack alert configuration

Both the daily pipeline and the TradingView strategy alerts deliver through one **Slack incoming webhook**.

### 1. Create the Slack incoming webhook

1. In Slack: **Settings & administration → Apps → Manage apps → Build → Incoming Webhooks** (or browse `api.slack.com/apps` and create an app with incoming webhooks enabled).
2. Pick the target channel and copy the webhook URL (`https://hooks.slack.com/services/…`).

### 2. Add it to GitHub Actions

1. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `SLACK_WEBHOOK_URL`, value: the webhook URL from step 1.
3. The `.github/workflows/fx-daily.yml` workflow reads it from the secrets store — it is never hardcoded. Without it, a run still archives the daily CSV but exits non-zero and posts nothing.

### 3. Point TradingView alerts at the same webhook

1. Open a major-pair chart, load the Pine strategy (see above).
2. Create an alert on the strategy, tick **Webhook URL**, and paste the same Slack webhook URL.
3. The strategy's `alert()` messages are Slack-ready JSON, so they post directly into the channel — no receiver server needed.

### Running locally

```bash
python -m pipelines.fx_daily --dry-run                 # live fetch, prints payloads, sends nothing
python -m pipelines.fx_daily --dry-run --fixture tests/fixtures/ohlc.csv   # fully offline
python -m pipelines.fx_daily                           # live: fetch, archive, post to Slack
```

`--dry-run` never touches the webhook secret; `--fixture` (the checked-in fixture) makes it work with no network at all. The alpha-alert threshold defaults to 80; tune with `--alpha-threshold`.

## Daily archive

Each live run appends `data/fx/YYYY-MM-DD.csv` — one file per session, 7 rows, schema `date,symbol,open,high,low,close,chg_1d,chg_5d,chg_21d,don20_state,don55_state,alpha_score` (QUOTE_ALL). Re-running for the same session never duplicates: an existing file is left untouched and the snapshot is committed by the workflow itself.

## Development

```bash
pip install ".[dev]"
ruff check .
pytest
```
