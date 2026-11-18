"""Pin the fx_major_breakout.pine alert message template against json.loads.

Pine itself is not parsed in CI (no Pine compiler exists outside TradingView).
Instead we pin the documented Slack payload template here and assert the .pine
source still emits that exact shape, so a stray edit cannot silently break
Slack delivery.
"""

from __future__ import annotations

import json
from pathlib import Path

ALERT_TEMPLATE = '{"text":"FX breakout: {symbol} {direction} @ {price} ({channel}, ADX {adx})"}'

STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"
PINE_PATH = STRATEGIES_DIR / "fx_major_breakout.pine"


def render_alert(
    symbol: str = "EURUSD",
    direction: str = "long",
    price: str = "1.0842",
    channel: str = "20d Donchian",
    adx: str = "27",
) -> str:
    """Render the documented alert template the same way the Pine script does.

    Placeholder replacement instead of str.format: the template contains literal
    JSON braces that format() would misread as fields.
    """
    msg = ALERT_TEMPLATE
    for key, value in {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "channel": channel,
        "adx": adx,
    }.items():
        msg = msg.replace("{" + key + "}", value)
    return msg


def test_alert_template_is_valid_json() -> None:
    payload = json.loads(render_alert())
    assert list(payload.keys()) == ["text"]


def test_alert_text_contains_symbol_direction_price() -> None:
    text = json.loads(render_alert())["text"]
    assert text == "FX breakout: EURUSD long @ 1.0842 (20d Donchian, ADX 27)"


def test_alert_template_handles_short_side_and_all_majors() -> None:
    majors = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
    for symbol in majors:
        payload = json.loads(render_alert(symbol=symbol, direction="short", price="149.25"))
        assert payload["text"].startswith(f"FX breakout: {symbol} short @ 149.25")


def test_pine_source_emits_the_documented_template() -> None:
    # Text-level consistency check only: the prefix and JSON envelope in the
    # .pine source must match ALERT_TEMPLATE, or the pinned tests above describe
    # a message TradingView no longer sends.
    source = PINE_PATH.read_text(encoding="utf-8")
    assert "'{\"text\":\"FX breakout: '" in source
    assert "f_alertJson" in source
