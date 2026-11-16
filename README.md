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

Coming in an upcoming PR (`.github/workflows/fx-daily.yml`). The pipeline will need one secret:

- `SLACK_WEBHOOK_URL` — a Slack incoming webhook URL, stored as a GitHub Actions secret. The daily workflow posts one Block Kit report message per session, plus separate alert messages only when a fresh 20d/55d breakout or a qualifying alpha score occurs.

## Development

```bash
pip install ".[dev]"
ruff check .
pytest
```
