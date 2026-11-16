"""Daily FX report and alpha-alert pipeline.

Fetches daily OHLC for the 7 major pairs from Yahoo Finance, computes per-pair
metrics (changes, Donchian states, alpha score), posts a Block Kit report plus
qualifying alpha alerts to Slack, and archives a daily CSV snapshot.

Pure metric/score/payload functions live here; the side effects (yfinance,
HTTP, filesystem) are isolated in named edge functions so every decision is
unit-testable offline against checked-in fixtures.

All signals are informational research output — not trading advice.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

SYMBOLS: tuple[str, ...] = (
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "USDCHF=X",
    "AUDUSD=X",
    "USDCAD=X",
    "NZDUSD=X",
)

CSV_SCHEMA = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "chg_1d",
    "chg_5d",
    "chg_21d",
    "don20_state",
    "don55_state",
    "alpha_score",
)

DON_HIGH = "new-high"
DON_LOW = "new-low"
DON_INSIDE = "inside"

# Minimum closes needed: 55-day Donchian window + current bar.
MIN_CLOSES = 56

DEFAULT_ALPHA_THRESHOLD = 80
DISCLAIMER = (
    "Alpha score: 0-100 rank-normalized composite of 1-month momentum, trend "
    "alignment and breakout proximity across the 7 majors. Informational "
    "research only — not trading advice."
)


@dataclass(frozen=True)
class PairMetrics:
    """Per-pair metrics for the latest session. Pure data, no behavior."""

    symbol: str
    session_date: str
    open: float
    high: float
    low: float
    close: float
    chg_1d: float
    chg_5d: float
    chg_21d: float
    don20_state: str
    don55_state: str
    # Raw alpha components (pre-ranking), kept so scoring stays inspectable.
    trend_alignment: float
    breakout_proximity: float


# --- Pure metric helpers ----------------------------------------------------


def pct_change(latest: float, earlier: float) -> float:
    """Percent change from an earlier price to the latest, in percent."""
    return (latest / earlier - 1.0) * 100.0


def donchian_state(close: float, prior_closes: Sequence[float]) -> str:
    """Close vs the high/low of the prior window: new-high, new-low or inside."""
    window_high = max(prior_closes)
    window_low = min(prior_closes)
    if close > window_high:
        return DON_HIGH
    if close < window_low:
        return DON_LOW
    return DON_INSIDE


def _sign(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def trend_alignment(close: float, closes: Sequence[float]) -> float:
    """Directional agreement in [-1, 1] of close-vs-SMA20, SMA20-vs-SMA50, 21d momentum."""
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    momentum_21d = pct_change(close, closes[-22])
    votes = (
        _sign(close - sma20),
        _sign(sma20 - sma50),
        _sign(momentum_21d),
    )
    return sum(votes) / len(votes)


def breakout_proximity(close: float, prior_closes: Sequence[float]) -> float:
    """Position of the close within the prior 20-day range: 0 = at the low, 1 = at the high.

    A flat window (zero range) carries no proximity information; 0.5 is neutral.
    """
    window_high = max(prior_closes)
    window_low = min(prior_closes)
    if window_high == window_low:
        return 0.5
    return (close - window_low) / (window_high - window_low)


def compute_metrics(symbol: str, frame: pd.DataFrame) -> PairMetrics:
    """Compute latest-session metrics from a daily OHLC frame (date-indexed, lowercase columns)."""
    closes = [float(c) for c in frame["close"].tolist()]
    if len(closes) < MIN_CLOSES:
        raise ValueError(
            f"need at least {MIN_CLOSES} daily closes, got {len(closes)}"
        )
    close = closes[-1]
    prior20 = closes[-21:-1]
    prior55 = closes[-56:-1]
    last = frame.iloc[-1]
    return PairMetrics(
        symbol=symbol,
        session_date=str(pd.Timestamp(frame.index[-1]).date()),
        open=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        close=close,
        chg_1d=pct_change(close, closes[-2]),
        chg_5d=pct_change(close, closes[-6]),
        chg_21d=pct_change(close, closes[-22]),
        don20_state=donchian_state(close, prior20),
        don55_state=donchian_state(close, prior55),
        trend_alignment=trend_alignment(close, closes),
        breakout_proximity=breakout_proximity(close, prior20),
    )


# --- Alpha scoring ----------------------------------------------------------


def rank_normalize(values: dict[str, float]) -> dict[str, float]:
    """Average-rank normalize to [0, 1] across the given pairs; ties share a rank."""
    n = len(values)
    if n <= 1:
        return dict.fromkeys(values, 0.5)
    ordered = sorted(values.items(), key=lambda item: item[1])
    scores: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        zero_based_avg_rank = (i + j) / 2
        for k in range(i, j + 1):
            scores[ordered[k][0]] = zero_based_avg_rank / (n - 1)
        i = j + 1
    return scores


def score_pairs(metrics: Sequence[PairMetrics]) -> dict[str, int]:
    """Rank-normalized 0-100 alpha composite across the pairs. Pure: same inputs, same scores."""
    momentum = {m.symbol: m.chg_21d for m in metrics}
    alignment = {m.symbol: m.trend_alignment for m in metrics}
    proximity = {m.symbol: m.breakout_proximity for m in metrics}
    rank_m = rank_normalize(momentum)
    rank_a = rank_normalize(alignment)
    rank_p = rank_normalize(proximity)
    return {
        symbol: round((rank_m[symbol] + rank_a[symbol] + rank_p[symbol]) / 3 * 100)
        for symbol in momentum
    }


# --- Slack payload builders (pure) ------------------------------------------


def build_report_message(
    session_date: str,
    metrics: Sequence[PairMetrics],
    scores: dict[str, int],
    failed_symbols: Sequence[str],
) -> dict:
    """One Block Kit message: header, one section per pair, footer with scores."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"FX Daily Report — {session_date}"},
        }
    ]
    for m in metrics:
        text = (
            f"*{m.symbol}* close {m.close:.5f} "
            f"({m.chg_1d:+.2f}% 1d, {m.chg_5d:+.2f}% 5d, {m.chg_21d:+.2f}% 21d) · "
            f"20d {m.don20_state} · 55d {m.don55_state} · alpha {scores[m.symbol]}"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    if failed_symbols:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚠️ Data unavailable for: {', '.join(failed_symbols)}",
                },
            }
        )
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": DISCLAIMER}]}
    )
    return {"blocks": blocks}


def build_alert_messages(
    metrics: Sequence[PairMetrics],
    scores: dict[str, int],
    alpha_threshold: int,
) -> list[dict]:
    """Plain {"text": ...} payloads, one per pair with a fresh breakout or alpha >= threshold."""
    alerts: list[dict] = []
    for m in metrics:
        reasons: list[str] = []
        if m.don20_state == DON_HIGH:
            reasons.append("new 20d high")
        if m.don20_state == DON_LOW:
            reasons.append("new 20d low")
        if m.don55_state == DON_HIGH:
            reasons.append("new 55d high")
        if m.don55_state == DON_LOW:
            reasons.append("new 55d low")
        if not reasons and scores[m.symbol] >= alpha_threshold:
            alerts.append(
                {
                    "text": (
                        f"⚠️ FX alpha alert — {m.symbol} alpha score "
                        f"{scores[m.symbol]} >= {alpha_threshold}"
                    )
                }
            )
        elif reasons:
            alerts.append(
                {
                    "text": (
                        f"⚠️ FX alpha alert — {m.symbol} {', '.join(reasons)}, "
                        f"alpha score {scores[m.symbol]}"
                    )
                }
            )
    return alerts


# --- CSV archive (filesystem edge) ------------------------------------------


def write_archive(
    archive_dir: str, metrics: Sequence[PairMetrics], scores: dict[str, int]
) -> str | None:
    """Write data/fx/YYYY-MM-DD.csv; return the path, or None when it already exists."""
    if not metrics:
        return None
    session_date = max(m.session_date for m in metrics)
    path = os.path.join(archive_dir, f"{session_date}.csv")
    if os.path.exists(path):
        return None
    os.makedirs(archive_dir, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(CSV_SCHEMA)
        for m in sorted(metrics, key=lambda item: item.symbol):
            writer.writerow(
                [
                    m.session_date,
                    m.symbol,
                    m.open,
                    m.high,
                    m.low,
                    m.close,
                    m.chg_1d,
                    m.chg_5d,
                    m.chg_21d,
                    m.don20_state,
                    m.don55_state,
                    scores[m.symbol],
                ]
            )
    return path


# --- Network edges ----------------------------------------------------------


def fetch_pair_history(symbol: str) -> pd.DataFrame:
    """Fetch ~6 months of daily OHLC from Yahoo Finance. Raises on any failure."""
    import yfinance as yf  # imported here: network edge, keeps module import offline-safe

    frame = yf.download(symbol, period="6mo", interval="1d", progress=False, auto_adjust=False)
    if frame is None or frame.empty:
        raise ValueError("no data returned")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.droplevel(1)
    frame.columns = [str(col).lower() for col in frame.columns]
    return frame[["open", "high", "low", "close"]]


def send_to_slack(webhook_url: str, payload: dict) -> None:
    """POST one payload to a Slack incoming webhook. Raises on a non-2xx response."""
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30):
        pass  # urlopen raises HTTPError on non-2xx; a 2xx body is not needed


# --- Data collection --------------------------------------------------------


def load_fixture(path: str) -> dict[str, pd.DataFrame]:
    """Load a long-format fixture CSV (date,symbol,open,high,low,close) into per-pair frames."""
    frame = pd.read_csv(path, parse_dates=["date"])
    frames: dict[str, pd.DataFrame] = {}
    for symbol, group in frame.groupby("symbol"):
        ordered = group.sort_values("date").set_index("date")
        frames[str(symbol)] = ordered[["open", "high", "low", "close"]]
    return frames


def fetch_all(symbols: Sequence[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Fetch every pair; a failed pair is reported and skipped, never a crashed run."""
    frames: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for symbol in symbols:
        try:
            frames[symbol] = fetch_pair_history(symbol)
        except Exception as exc:  # noqa: BLE001 - any fetch failure means "no data for this pair"
            print(f"error: fetch failed for {symbol}: {exc}", file=sys.stderr)
            failed.append(symbol)
    return frames, failed


def compute_all(frames: dict[str, pd.DataFrame]) -> tuple[list[PairMetrics], list[str]]:
    """Compute metrics per pair; a pair with bad/short data is reported and skipped."""
    metrics: list[PairMetrics] = []
    failed: list[str] = []
    for symbol in SYMBOLS:
        frame = frames.get(symbol)
        if frame is None:
            failed.append(symbol)
            continue
        try:
            metrics.append(compute_metrics(symbol, frame))
        except Exception as exc:  # noqa: BLE001 - surfaced below, never silently dropped
            print(f"error: could not compute metrics for {symbol}: {exc}", file=sys.stderr)
            failed.append(symbol)
    return metrics, failed


# --- CLI --------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pipelines.fx_daily",
        description="Daily FX report + alpha alerts to Slack (informational research only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact Slack payloads to stdout; no Slack send, no webhook access",
    )
    parser.add_argument(
        "--fixture",
        help="path to a fixture OHLC CSV (date,symbol,open,high,low,close); offline mode",
    )
    parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=DEFAULT_ALPHA_THRESHOLD,
        help=f"alert when alpha score >= this value (default {DEFAULT_ALPHA_THRESHOLD})",
    )
    parser.add_argument("--archive-dir", default=os.path.join("data", "fx"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.fixture:
        frames: dict[str, pd.DataFrame] = load_fixture(args.fixture)
        fetch_failed: list[str] = []
    else:
        frames, fetch_failed = fetch_all(SYMBOLS)

    metrics, compute_failed = compute_all(frames)
    failed_symbols = sorted(set(fetch_failed) | set(compute_failed))
    scores = score_pairs(metrics)
    session_date = max((m.session_date for m in metrics), default="")
    report = build_report_message(session_date, metrics, scores, failed_symbols)
    alerts = build_alert_messages(metrics, scores, args.alpha_threshold)

    if args.dry_run:
        print(json.dumps({"report": report, "alerts": alerts}, indent=2))
        return 0

    if not metrics:
        print("error: no pairs produced metrics; nothing to report", file=sys.stderr)
        return 1

    archive_path = write_archive(args.archive_dir, metrics, scores)
    if archive_path is None:
        print(f"archive: {session_date}.csv already exists; skipped")
    else:
        print(f"archive: wrote {archive_path}")

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print(
            "error: SLACK_WEBHOOK_URL is not set — add it as a repo secret and pass it "
            "through the workflow env (data archive was still written)",
            file=sys.stderr,
        )
        return 1

    send_errors: list[str] = []
    try:
        send_to_slack(webhook_url, report)
        print(f"slack: posted report ({len(metrics)} pairs)")
    except Exception as exc:  # noqa: BLE001 - report every send failure, fail at the end
        send_errors.append(f"report: {exc}")
    for alert in alerts:
        try:
            send_to_slack(webhook_url, alert)
            print(f"slack: posted alert: {alert['text']}")
        except Exception as exc:  # noqa: BLE001
            send_errors.append(f"{alert['text']}: {exc}")
    for error in send_errors:
        print(f"error: slack send failed — {error}", file=sys.stderr)
    return 1 if send_errors else 0


if __name__ == "__main__":
    sys.exit(main())
