from datetime import UTC, date, datetime

from conftest import FINAL, NAMES
from myfinsight.report.assembler import (
    LIMIT_INTERIM_CHANGES,
    LIMIT_PAST_PERFORMANCE,
    LIMIT_SURVIVORSHIP,
    REQUIRED_SECTIONS,
    assemble_report,
    last_regular_change_date,
)
from myfinsight.report.display import format_path
from myfinsight.report.evidence import build_evidence, contains_advice

CREATED = datetime(2026, 10, 5, 1, 2, 3, tzinfo=UTC)


def make_report(sc, **over):
    evidence = build_evidence(universe=sc.universe, weights=sc.weights, quality=sc.quality,
                              metrics=sc.metrics, profile=sc.profile, price_meta=sc.price_meta,
                              spec=sc.spec)
    kw = dict(run_id="20261005-010203-abcdef", created_at=CREATED, profile=sc.profile,
              spec=sc.spec, weights=sc.weights, backtest=sc.backtest, metrics=sc.metrics,
              evidence=evidence, universe=sc.universe, quality=sc.quality, steps=sc.steps,
              names=NAMES)
    kw.update(over)
    return assemble_report(**kw)


def test_required_sections_in_order(scenario):
    text = make_report(scenario).text_markdown
    positions = [text.index(s) for s in REQUIRED_SECTIONS]
    assert positions == sorted(positions)


def test_same_input_same_text(scenario):
    assert make_report(scenario).text_markdown == make_report(scenario).text_markdown


def test_allocation_amounts(scenario):
    report = make_report(scenario)
    rows = report.data.allocation
    assert [r.ticker for r in rows] == ["AAPL", "MSFT", "AVGO", "NVDA", "ORCL"]
    assert {r.ticker: r.weight for r in rows} == FINAL
    total_krw = sum(r.amount_krw for r in rows)
    assert abs(total_krw - scenario.profile.investment_amount_krw) <= len(rows)
    assert rows[0].name == "Apple Inc."


def test_display_values_match_rules_and_text(scenario):
    report = make_report(scenario)
    for path, shown in report.display_values.items():
        assert shown == format_path(report.data, path)
        assert shown in report.text_markdown
    assert report.display_values["allocation.NVDA.weight"] == "15.0%"
    assert report.display_values["metrics.strategy.mdd"] == "-22.45%"
    assert report.display_values["metrics.strategy.total_return"] == "+81.23%"
    assert "| NVDA | NVIDIA Corp. | 15.0% |" in report.text_markdown


def test_limitations(scenario):
    data = make_report(scenario, extra_limitations=["구성종목 갱신 실패: 기존 스냅샷 사용"]).data
    assert data.limitations[:2] == [LIMIT_PAST_PERFORMANCE, LIMIT_SURVIVORSHIP]
    assert any("C99" in t for t in data.limitations)
    assert LIMIT_INTERIM_CHANGES in data.limitations
    assert "구성종목 갱신 실패: 기존 스냅샷 사용" in data.limitations
    # 스냅샷 2026-09-21 ≥ 정기 변경일 2026-09-18 → 노후 경고 없음
    assert not any("정기 변경일" in t and "오래" in t for t in data.limitations)


def test_stale_snapshot_limitation(scenario):
    uni = scenario.universe.model_copy(update={"snapshot_dates": {
        k: date(2026, 6, 30) for k in scenario.universe.snapshot_dates}})
    report = make_report(scenario, universe=uni)
    assert any("2026-06-30" in t and "2026-09-18" in t for t in report.data.limitations)
    assert "⚠ 제외·한계 사항" in report.text_markdown


def test_last_regular_change_date():
    assert last_regular_change_date(date(2026, 10, 5)) == date(2026, 9, 18)
    assert last_regular_change_date(date(2026, 9, 18)) == date(2026, 9, 18)
    assert last_regular_change_date(date(2026, 9, 17)) == date(2026, 6, 19)
    assert last_regular_change_date(date(2027, 1, 10)) == date(2026, 12, 18)


def test_no_advice_and_sources_shown(scenario):
    text = make_report(scenario).text_markdown
    assert not contains_advice(text)
    assert "출처: yfinance 수정종가" in text
    assert "METRIC_UNDEFINED" not in text


def test_sharpe_undefined_displayed(scenario):
    m = scenario.metrics.model_copy(update={
        "strategy": scenario.metrics.strategy.model_copy(update={"sharpe": None})})
    report = make_report(scenario, metrics=m)
    assert report.display_values["metrics.strategy.sharpe"] == "METRIC_UNDEFINED"
