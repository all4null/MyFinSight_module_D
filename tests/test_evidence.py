from datetime import date

from conftest import FINAL, PRE_CAP
from myfinsight.report.evidence import build_evidence, contains_advice
from myfinsight.schemas import SelectionRule, SelectionSpec, TickerSignal
from myfinsight.schemas.results import METRIC_MOMENTUM


def _build(sc, **over):
    kw = dict(universe=sc.universe, weights=sc.weights, quality=sc.quality, metrics=sc.metrics,
              profile=sc.profile, price_meta=sc.price_meta, spec=sc.spec)
    kw.update(over)
    return build_evidence(**kw)


def test_every_selected_ticker_has_selection_and_weight(scenario):
    items = _build(scenario)
    for t in FINAL:
        kinds = {e.kind for e in items if e.subject == t}
        assert {"selection", "weight"} <= kinds


def test_all_items_have_source_and_as_of_and_no_advice(scenario):
    for e in _build(scenario):
        assert e.source.strip()
        assert isinstance(e.as_of, date)
        assert not contains_advice(e.statement)


def test_low_vol_statement_and_values(scenario):
    items = _build(scenario)
    msft = next(e for e in items if e.subject == "MSFT" and e.kind == "selection")
    assert msft.statement == (
        "MSFT: 최근 252거래일 연환산 변동성 21.00%, 후보 20개 중 1위 → 저변동성 상위 5개에 포함"
    )
    assert msft.values["signal.ann_volatility"] == 0.21
    assert msft.values["rank.ann_volatility"] == 1
    assert msft.source == "yfinance 수정종가"


def test_cap_items(scenario):
    items = _build(scenario)
    caps = {e.subject: e for e in items if e.kind == "cap"}
    assert set(caps) == {t for t in FINAL if abs(FINAL[t] - PRE_CAP[t]) > 1e-9}
    assert caps["NVDA"].statement == "NVDA: 상한 15.0% 적용으로 30.0% → 15.0%"
    assert "재분배" in caps["MSFT"].statement
    assert caps["MSFT"].values["weight.final"] == 0.25


def test_universe_and_limitation(scenario):
    items = _build(scenario)
    uni = items[0]
    assert uni.kind == "universe"
    assert uni.statement == (
        "S&P 500·Nasdaq-100 구성종목(2026-09-21 기준) 중 관심산업 AI, 반도체, 클라우드에 "
        "해당하는 20개 종목을 후보로 사용했습니다."
    )
    lim = [e for e in items if e.kind == "limitation"]
    assert [e.subject for e in lim] == ["C99"]
    assert lim[0].values["coverage"] == 0.9


def test_mdd_within_and_exceeding(scenario):
    within = next(e for e in _build(scenario) if "최대낙폭" in e.statement)
    assert "-30.00% 이내입니다" in within.statement
    worse = scenario.metrics.model_copy(
        update={"strategy": scenario.metrics.strategy.model_copy(update={"mdd": -0.35})}
    )
    exceed = next(e for e in _build(scenario, metrics=worse) if "최대낙폭" in e.statement)
    assert "-30.00%를 초과합니다" in exceed.statement
    assert exceed.values["metrics.strategy.mdd"] == -0.35


def test_momentum_and_fixed_list_templates(scenario):
    mom_spec = scenario.spec.model_copy(update={"selection": SelectionSpec(
        rule=SelectionRule.MOMENTUM_TOP_N, params={"n": 5, "lookback_days": 252, "skip_days": 21})})
    sigs = [TickerSignal(ticker=t, metric_name=METRIC_MOMENTUM, value=0.1 * (i + 1),
                         rank=5 - i, universe_size=20) for i, t in enumerate(sorted(FINAL))]
    w = scenario.weights.model_copy(update={"signals": sigs})
    items = _build(scenario, spec=mom_spec, weights=w)
    aapl = next(e for e in items if e.subject == "AAPL" and e.kind == "selection")
    assert aapl.statement.startswith(
        "AAPL: 252거래일 수익률(최근 21일 제외) +10.00%, 후보 20개 중 5위"
    )

    fixed_spec = scenario.spec.model_copy(update={"selection": SelectionSpec(
        rule=SelectionRule.FIXED_LIST, params={"tickers": sorted(FINAL)})})
    items = _build(scenario, spec=fixed_spec)
    assert next(e for e in items if e.subject == "AAPL" and e.kind == "selection").statement == (
        "AAPL: 전략에 지정된 종목"
    )


def test_deterministic(scenario):
    assert _build(scenario) == _build(scenario)
