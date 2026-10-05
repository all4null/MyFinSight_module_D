"""M06-01 근거 생성기 (FR26, FR05).

템플릿으로만 근거 문장을 만든다 (LLM 미사용, C-08). 문장의 모든 숫자는 ``values`` 에 원본을
저장하고, 표시는 부록 D 규칙(:mod:`myfinsight.report.display`)을 따른다.

``values`` 의 키 중 아래 "참조 키"는 M04-03 CONSIST_EVIDENCE가 원본과 대조한다.

- ``signal.<metric_name>`` / ``rank.<metric_name>``: WeightSet.signals 의 해당 티커 지표값·순위
- ``weight.pre_cap`` / ``weight.final``: WeightSet.pre_cap_weights / weights 의 해당 티커 값
- ``metrics.<path>``: MetricsBundle 의 필드 (예: ``metrics.strategy.mdd``)

그 밖의 키(``lookback_days``, ``n`` 등)는 문장에 쓰인 파라미터 기록이다.
"""

from __future__ import annotations

from datetime import date

from myfinsight.report.display import fmt_date, fmt_pct, fmt_weight
from myfinsight.schemas.enums import IndexCode, SelectionRule, WeightingRule
from myfinsight.schemas.market import DataQualityReport, PriceMeta, UniverseResult
from myfinsight.schemas.profile import UserProfile
from myfinsight.schemas.report import EvidenceItem
from myfinsight.schemas.results import (
    METRIC_MOMENTUM,
    METRIC_VOLATILITY,
    MetricsBundle,
    TickerSignal,
    WeightSet,
)
from myfinsight.schemas.spec import StrategySpec

CAP_TOLERANCE = 1e-9

INDEX_DISPLAY_NAMES: dict[IndexCode, str] = {
    IndexCode.SP500: "S&P 500",
    IndexCode.NDX: "Nasdaq-100",
}

WEIGHTING_DISPLAY_NAMES: dict[WeightingRule, str] = {
    WeightingRule.EQUAL: "동일 비중",
    WeightingRule.INVERSE_VOL: "변동성 역가중",
}

SELECTION_DISPLAY_NAMES: dict[SelectionRule, str] = {
    SelectionRule.FIXED_LIST: "고정 목록",
    SelectionRule.LOW_VOL_TOP_N: "저변동성 상위 N",
    SelectionRule.MOMENTUM_TOP_N: "모멘텀 상위 N",
}

# 투자 권유 표현 금지 (M06-01 제약)
BANNED_PHRASES: tuple[str, ...] = (
    "사세요", "파세요", "유망", "추천합니다", "매수 추천", "매도 추천",
)

_SELECTION_METRIC: dict[SelectionRule, str] = {
    SelectionRule.LOW_VOL_TOP_N: METRIC_VOLATILITY,
    SelectionRule.MOMENTUM_TOP_N: METRIC_MOMENTUM,
}


def contains_advice(text: str) -> bool:
    """문장에 투자 권유 표현이 있으면 True."""
    return any(p in text for p in BANNED_PHRASES)


def price_source_label(meta: PriceMeta) -> str:
    """가격 데이터 출처 표시 문자열."""
    return f"{meta.source} 수정종가"


def _find_signal(signals: list[TickerSignal], ticker: str, metric: str) -> TickerSignal | None:
    ranked = [s for s in signals if s.ticker == ticker and s.metric_name == metric]
    ranked.sort(key=lambda s: (s.rank is None, s.rank or 0))
    return ranked[0] if ranked else None


def _universe_item(
    universe: UniverseResult, spec: StrategySpec, profile: UserProfile, as_of: date
) -> EvidenceItem:
    k = len(universe.tickers)
    if spec.universe.mode == "fixed":
        statement = f"전략에 지정된 고정 목록 {k}개 종목을 후보로 사용했습니다."
        values: dict[str, float | str] = {"k": k, "mode": "fixed"}
        return EvidenceItem(
            subject="universe", kind="universe", statement=statement, values=values,
            source=universe.source, as_of=as_of,
        )

    indices = [c for c in IndexCode if c in universe.snapshot_dates]  # SP500 우선
    index_names = "·".join(INDEX_DISPLAY_NAMES.get(c, c.value) for c in indices)
    snap = max(universe.snapshot_dates.values()) if universe.snapshot_dates else as_of
    snap_text = fmt_date(snap)
    industries = ", ".join(profile.interest_industries)
    values = {"k": k, "snapshot_date": snap_text, "indices": index_names}
    if industries:
        values["industries"] = industries
        statement = (
            f"{index_names} 구성종목({snap_text} 기준) 중 관심산업 {industries}에 해당하는 "
            f"{k}개 종목을 후보로 사용했습니다."
        )
    else:
        statement = (
            f"{index_names} 구성종목({snap_text} 기준) 중 {k}개 종목을 후보로 사용했습니다 "
            "(관심산업 필터 없음)."
        )
    return EvidenceItem(
        subject="universe", kind="universe", statement=statement, values=values,
        source=universe.source, as_of=snap,
    )


def _selection_item(
    ticker: str, spec: StrategySpec, weights: WeightSet, source: str, as_of: date
) -> EvidenceItem:
    rule = spec.selection.rule
    params = spec.selection.params
    if rule == SelectionRule.FIXED_LIST:
        return EvidenceItem(
            subject=ticker, kind="selection", statement=f"{ticker}: 전략에 지정된 종목",
            values={"rule": rule.value}, source=f"Strategy Spec {spec.spec_id}", as_of=as_of,
        )

    metric = _SELECTION_METRIC[rule]
    sig = _find_signal(weights.signals, ticker, metric)
    lookback = int(params.get("lookback_days", 252))
    n = int(params.get("n", 5))
    if sig is None or sig.rank is None:
        statement = (
            f"{ticker}: {SELECTION_DISPLAY_NAMES[rule]} 규칙으로 선정 (지표값 기록 없음)"
        )
        return EvidenceItem(
            subject=ticker, kind="selection", statement=statement,
            values={"rule": rule.value, "n": n, "lookback_days": lookback},
            source=source, as_of=as_of,
        )

    values: dict[str, float | str] = {
        f"signal.{metric}": sig.value,
        f"rank.{metric}": sig.rank,
        "universe_size": sig.universe_size,
        "lookback_days": lookback,
        "n": n,
    }
    if rule == SelectionRule.LOW_VOL_TOP_N:
        statement = (
            f"{ticker}: 최근 {lookback}거래일 연환산 변동성 {fmt_pct(sig.value)}, "
            f"후보 {sig.universe_size}개 중 {sig.rank}위 → 저변동성 상위 {n}개에 포함"
        )
    else:
        skip = int(params.get("skip_days", 21))
        values["skip_days"] = skip
        statement = (
            f"{ticker}: {lookback}거래일 수익률(최근 {skip}일 제외) "
            f"{fmt_pct(sig.value, signed=True)}, 후보 {sig.universe_size}개 중 {sig.rank}위 "
            f"→ 모멘텀 상위 {n}개에 포함"
        )
    return EvidenceItem(
        subject=ticker, kind="selection", statement=statement, values=values,
        source=source, as_of=as_of,
    )


def _weight_items(
    ticker: str, spec: StrategySpec, weights: WeightSet, source: str
) -> list[EvidenceItem]:
    rule_name = WEIGHTING_DISPLAY_NAMES.get(spec.weighting.rule, spec.weighting.rule.value)
    final = weights.weights.get(ticker, 0.0)
    pre = weights.pre_cap_weights.get(ticker, final)
    items = [
        EvidenceItem(
            subject=ticker, kind="weight",
            statement=f"{ticker}: {rule_name} 방식으로 {fmt_weight(pre)}",
            values={"weight.pre_cap": pre, "rule": spec.weighting.rule.value},
            source=source, as_of=weights.as_of,
        )
    ]
    if abs(pre - final) > CAP_TOLERANCE:
        c = spec.constraints
        cap = min(c.max_weight_all, c.max_weight_per_ticker.get(ticker, c.max_weight_all))
        if pre > cap + CAP_TOLERANCE:
            statement = (
                f"{ticker}: 상한 {fmt_weight(cap)} 적용으로 {fmt_weight(pre)} → {fmt_weight(final)}"
            )
        else:
            statement = (
                f"{ticker}: 다른 종목의 상한 초과분 재분배로 {fmt_weight(pre)} → "
                f"{fmt_weight(final)}"
            )
        items.append(
            EvidenceItem(
                subject=ticker, kind="cap", statement=statement,
                values={"cap": cap, "weight.pre_cap": pre, "weight.final": final},
                source=f"Strategy Spec {spec.spec_id} 제약조건", as_of=weights.as_of,
            )
        )
    return items


def _metric_items(
    metrics: MetricsBundle, profile: UserProfile, spec: StrategySpec, source: str, as_of: date
) -> list[EvidenceItem]:
    s = metrics.strategy
    loss_tol = profile.loss_tolerance_pct
    within = -s.mdd * 100 <= loss_tol
    tol_text = f"-{fmt_pct(loss_tol / 100)}"
    verdict = f"{tol_text} 이내입니다" if within else f"{tol_text}를 초과합니다"
    mdd_item = EvidenceItem(
        subject="portfolio", kind="metric",
        statement=(
            f"Backtest 기간 최대낙폭 {fmt_pct(s.mdd, signed=True)}"
            f"({fmt_date(s.mdd_peak)}~{fmt_date(s.mdd_trough)})는 "
            f"투자성향의 손실 감내 수준 {verdict}."
        ),
        values={
            "metrics.strategy.mdd": s.mdd,
            "loss_tolerance_pct": loss_tol,
            "within_tolerance": "yes" if within else "no",
        },
        source=source, as_of=as_of,
    )
    ret_item = EvidenceItem(
        subject="portfolio", kind="metric",
        statement=(
            f"Backtest 누적수익률 {fmt_pct(s.total_return, signed=True)}, "
            f"Benchmark({spec.benchmark}) {fmt_pct(metrics.benchmark.total_return, signed=True)}, "
            f"초과 {fmt_pct(metrics.excess_total_return, signed=True)}."
        ),
        values={
            "metrics.strategy.total_return": s.total_return,
            "metrics.benchmark.total_return": metrics.benchmark.total_return,
            "metrics.excess_total_return": metrics.excess_total_return,
        },
        source=source, as_of=as_of,
    )
    return [mdd_item, ret_item]


def _limitation_items(quality: DataQualityReport, source: str) -> list[EvidenceItem]:
    coverage = {q.ticker: q.coverage for q in quality.items}
    items = []
    for ticker in sorted(quality.excluded):
        reason = quality.excluded[ticker]
        values: dict[str, float | str] = {"reason": reason}
        if ticker in coverage:
            values["coverage"] = coverage[ticker]
        items.append(
            EvidenceItem(
                subject=ticker, kind="limitation",
                statement=f"{ticker}: 데이터 부족으로 제외 ({reason})",
                values=values, source=f"{source} 품질 판정", as_of=quality.as_of,
            )
        )
    return items


def build_evidence(
    *,
    universe: UniverseResult,
    weights: WeightSet,
    quality: DataQualityReport,
    metrics: MetricsBundle,
    profile: UserProfile,
    price_meta: PriceMeta,
    spec: StrategySpec,
) -> list[EvidenceItem]:
    """근거 항목 목록을 만든다.

    순서: universe → 선정 종목(티커 오름차순)별 selection·weight·cap → metric → limitation.
    모든 항목에 ``source`` 와 ``as_of`` 가 붙는다.
    """
    source = price_source_label(price_meta)
    items: list[EvidenceItem] = [_universe_item(universe, spec, profile, weights.as_of)]
    for ticker in sorted(weights.selected):
        items.append(_selection_item(ticker, spec, weights, source, price_meta.as_of))
        items.extend(_weight_items(ticker, spec, weights, f"전략 규칙 계산 ({source})"))
    items.extend(
        _metric_items(metrics, profile, spec, f"Backtest 계산 ({source})", price_meta.as_of)
    )
    items.extend(_limitation_items(quality, source))
    return items
