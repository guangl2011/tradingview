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

Coming in an upcoming PR (`strategies/fx_major_breakout.pine`). High-level steps once it lands:

1. Open a major-pair chart on TradingView.
2. Open the Pine Editor, paste the strategy source, and click "Add to chart".
3. Review the Strategy Tester output.
4. Create an alert on the strategy and point the webhook at your Slack incoming-webhook URL.

## Slack alert configuration

Coming in an upcoming PR (`.github/workflows/fx-daily.yml`). The pipeline will need one secret:

- `SLACK_WEBHOOK_URL` — a Slack incoming webhook URL, stored as a GitHub Actions secret. The daily workflow posts one Block Kit report message per session, plus separate alert messages only when a fresh 20d/55d breakout or a qualifying alpha score occurs.

## Development

```bash
pip install ".[dev]"
ruff check .
pytest
```
