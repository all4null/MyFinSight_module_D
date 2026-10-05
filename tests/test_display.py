from datetime import date, datetime

import pytest

from myfinsight.report.display import (
    UNDEFINED_TEXT,
    fmt_date,
    fmt_krw,
    fmt_pct,
    fmt_sharpe,
    fmt_usd,
    fmt_weight,
    formatter_for,
    krw_amount,
    round_half_up,
)


@pytest.mark.parametrize(
    ("value", "signed", "expected"),
    [(0.1523, False, "15.23%"), (0.15234, True, "+15.23%"), (-0.031, True, "-3.10%"),
     (0.0, True, "0.00%"), (0.000049, True, "0.00%"), (0.00125, False, "0.13%")],
)
def test_pct(value, signed, expected):
    assert fmt_pct(value, signed=signed) == expected


def test_weight_and_money():
    assert fmt_weight(0.214) == "21.4%"
    assert fmt_weight(0.15) == "15.0%"
    assert fmt_krw(7_500_000) == "7,500,000원"
    assert fmt_usd(5432.1) == "$5,432.10"
    assert fmt_usd(2.675) == "$2.68"  # ROUND_HALF_UP (이진 부동소수 2.67499... 아님)
    assert fmt_sharpe(0.645) == "0.65"
    assert fmt_sharpe(None) == UNDEFINED_TEXT
    assert fmt_pct(None) == UNDEFINED_TEXT
    assert fmt_date(date(2026, 1, 2)) == "2026-01-02"
    assert fmt_date(datetime(2026, 1, 2, 3, 4)) == "2026-01-02"


def test_round_half_up_and_krw():
    assert round_half_up(0.5) == 1
    assert round_half_up(2.5) == 3
    assert round_half_up(-2.5) == -3
    assert krw_amount(1.0, 1380.5) == 1381


def test_formatter_rules():
    assert formatter_for("allocation.BRK-B.weight")(0.1) == "10.0%"
    assert formatter_for("metrics.strategy.cagr")(0.1) == "+10.00%"
    assert formatter_for("metrics.benchmark.ann_volatility")(0.1) == "10.00%"
    with pytest.raises(KeyError):
        formatter_for("metrics.strategy.unknown")
