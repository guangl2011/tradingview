"""Unit tests for the tradingview-fx scaffold."""


def test_scaffold() -> None:
    """Smoke test: pytest discovery works and the pipelines package imports."""
    import pipelines

    assert pipelines.__doc__ is not None
