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
