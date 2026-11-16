"""Unit tests for the FX daily pipeline, run against the checked-in fixture OHLC.

The fixture (tests/fixtures/ohlc.csv) is 70 business days ending 2026-11-13 for
all 7 majors, with flat two-block price patterns so the Donchian states and
changes are hand-computable (see the expected values below).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pipelines.fx_daily import (
    CSV_SCHEMA,
    DON_HIGH,
    DON_INSIDE,
    DON_LOW,
    build_alert_messages,
    build_report_message,
    compute_all,
    load_fixture,
    main,
    score_pairs,
    write_archive,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ohlc.csv"
SESSION_DATE = "2026-11-13"


@pytest.fixture(scope="module")
def fixture_metrics():
    frames = load_fixture(str(FIXTURE))
    metrics, failed = compute_all(frames)
    assert failed == []
    assert len(metrics) == 7
    return {m.symbol: m for m in metrics}


@pytest.fixture(scope="module")
def fixture_scores(fixture_metrics):
    return score_pairs(list(fixture_metrics.values()))


# --- Donchian states: hand-computed fixture expectations ---------------------


def test_donchian_states_match_hand_computed_fixture(fixture_metrics):
    expected = {
        # flat at 1.08 then close 1.09: above both prior windows
        "EURUSD=X": (DON_HIGH, DON_HIGH),
        # flat at 1.27 then close 1.26: below both prior windows
        "GBPUSD=X": (DON_LOW, DON_LOW),
        # close equals the flat history: strictly inside
        "USDJPY=X": (DON_INSIDE, DON_INSIDE),
        # close 1.242 inside 20d range [1.240, 1.245]
        "USDCHF=X": (DON_INSIDE, DON_INSIDE),
        # 20d window flat 0.650 (close 0.654 breaks it); 55d window reaches 0.660
        "AUDUSD=X": (DON_HIGH, DON_INSIDE),
        # 20d window flat 1.350 (close 1.349 breaks it); 55d window reaches 1.340
        "USDCAD=X": (DON_LOW, DON_INSIDE),
        # flat at 0.59 then close 0.588
        "NZDUSD=X": (DON_LOW, DON_LOW),
    }
    actual = {
        symbol: (m.don20_state, m.don55_state) for symbol, m in fixture_metrics.items()
    }
    assert actual == expected


def test_pct_changes_match_hand_computed_fixture(fixture_metrics):
    m = fixture_metrics["EURUSD=X"]
    assert m.session_date == SESSION_DATE
    assert m.close == pytest.approx(1.09)
    # 1.0900 / 1.0800 across the 1d, 5d and 21d lookbacks (flat history before the jump)
    assert m.chg_1d == pytest.approx(0.9259259, rel=1e-6)
    assert m.chg_5d == pytest.approx(0.9259259, rel=1e-6)
    assert m.chg_21d == pytest.approx(0.9259259, rel=1e-6)

    chf = fixture_metrics["USDCHF=X"]
    # close 1.2420 vs prior close 1.2450, and vs 1.2400 21 sessions ago
    assert chf.chg_1d == pytest.approx(-0.2409639, rel=1e-6)
    assert chf.chg_21d == pytest.approx(0.1612903, rel=1e-6)

    jpy = fixture_metrics["USDJPY=X"]
    assert jpy.chg_1d == 0.0
    assert jpy.chg_5d == 0.0
    assert jpy.chg_21d == 0.0


# --- Alpha score: deterministic, bounded, behaviorally ordered ---------------


def test_alpha_scores_deterministic_and_bounded(fixture_metrics, fixture_scores):
    assert score_pairs(list(fixture_metrics.values())) == fixture_scores  # same inputs, same output
    assert set(fixture_scores) == set(fixture_metrics)
    assert all(0 <= score <= 100 for score in fixture_scores.values())


def test_alpha_scores_rank_breakout_leader_first(fixture_metrics, fixture_scores):
    # EURUSD has the strongest 21d momentum (+0.93%), full trend alignment and
    # a fresh 20d+55d high: nothing else can outrank it. GBPUSD is its mirror.
    assert fixture_scores["EURUSD=X"] == max(fixture_scores.values())
    assert fixture_scores["GBPUSD=X"] == min(fixture_scores.values())


# --- Slack payloads ----------------------------------------------------------


def test_report_message_is_valid_block_kit_json(fixture_metrics, fixture_scores):
    report = build_report_message(
        SESSION_DATE, list(fixture_metrics.values()), fixture_scores, failed_symbols=[]
    )
    parsed = json.loads(json.dumps(report))  # JSON-serializable
    types = [block["type"] for block in parsed["blocks"]]
    assert types[0] == "header" and SESSION_DATE in parsed["blocks"][0]["text"]["text"]
    assert types.count("section") == 7  # one section per pair
    assert types[-1] == "context"


def test_report_message_surfaces_fetch_failures(fixture_metrics, fixture_scores):
    report = build_report_message(
        SESSION_DATE,
        list(fixture_metrics.values()),
        fixture_scores,
        failed_symbols=["USDJPY=X"],
    )
    assert json.loads(json.dumps(report))
    assert any("USDJPY=X" in block["text"]["text"] for block in report["blocks"])


def test_alert_messages_fire_on_fresh_breakout_or_high_score(
    fixture_metrics, fixture_scores
):
    alerts = build_alert_messages(list(fixture_metrics.values()), fixture_scores, 80)
    alerted_symbols = {alert["text"].split("— ")[1].split(" ")[0] for alert in alerts}
    # 5 pairs print fresh breakouts; USDJPY/USDCHF are inside with sub-80 scores.
    assert alerted_symbols == {
        "EURUSD=X",
        "GBPUSD=X",
        "AUDUSD=X",
        "USDCAD=X",
        "NZDUSD=X",
    }
    for alert in alerts:
        payload = json.loads(json.dumps(alert))
        assert set(payload) == {"text"}
        assert payload["text"].startswith("⚠️ FX alpha alert — ")
        assert "alpha score" in payload["text"]


def test_alert_messages_include_high_score_without_breakout(
    fixture_metrics, fixture_scores
):
    # Threshold 0: every pair qualifies, including the two inside-window pairs.
    alerts = build_alert_messages(list(fixture_metrics.values()), fixture_scores, 0)
    assert len(alerts) == 7
    assert any("USDJPY=X" in alert["text"] for alert in alerts)


# --- Archive writer ----------------------------------------------------------


def test_archive_writer_writes_seven_quoted_rows_and_is_idempotent(
    tmp_path, fixture_metrics, fixture_scores
):
    archive_dir = tmp_path / "fx"

    path = write_archive(str(archive_dir), list(fixture_metrics.values()), fixture_scores)
    assert path is not None
    written = Path(path)
    assert written.name == f"{SESSION_DATE}.csv"

    lines = written.read_text().strip().split("\n")
    assert len(lines) == 8  # header + 7 rows
    header = next(csv.reader(lines[:1]))
    assert tuple(header) == CSV_SCHEMA
    for line in lines:
        fields = next(csv.reader([line]))
        assert len(fields) == len(CSV_SCHEMA)
        assert line.startswith('"') and line.endswith('"')  # QUOTE_ALL

    rows = list(csv.DictReader(written.read_text().splitlines()))
    assert {row["symbol"] for row in rows} == set(fixture_metrics)
    assert rows[0]["date"] == SESSION_DATE

    # Re-run for the same session: no duplicate write.
    assert (
        write_archive(str(archive_dir), list(fixture_metrics.values()), fixture_scores)
        is None
    )
    assert len(list(archive_dir.iterdir())) == 1


# --- CLI: offline dry-run ----------------------------------------------------


def test_dry_run_offline_prints_exact_payloads_and_writes_nothing(tmp_path, capsys):
    archive_dir = tmp_path / "fx"

    exit_code = main(
        [
            "--dry-run",
            "--fixture",
            str(FIXTURE),
            "--archive-dir",
            str(archive_dir),
        ]
    )

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)  # stdout is one JSON document
    assert set(envelope) == {"report", "alerts"}
    json.loads(json.dumps(envelope["report"]))  # both payloads are valid JSON
    for alert in envelope["alerts"]:
        json.loads(json.dumps(alert))
    assert not archive_dir.exists()  # dry-run never writes the archive
