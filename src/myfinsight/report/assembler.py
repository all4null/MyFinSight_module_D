"""M06-02 Report 조립기 (FR14, UC003 부록 B).

1. ReportData 생성: 배분표 = 기준일 비중 × 초기자본(USD·원화), 한계 목록 자동 구성
2. Markdown 렌더링 (부록 B 번호, 6·9번은 프로토타입 제외 — 9는 요약의 템플릿 한 줄로 대체)
3. 렌더러는 텍스트와 함께 「표시값 목록」(경로 → 표시 문자열)을 돌려준다 (M04-03 CONSIST_TEXT)
4. 저장하지 않고 ``Report`` 만 반환한다. 저장은 M04-03 통과 후 M08-02가 수행한다.

숫자 표시는 부록 D 규칙만 쓰며, 새 값은 계산하지 않는다 (금액 = 비중 × 자본 곱셈만 허용).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta

from myfinsight.report.display import fmt_date, format_path, krw_amount
from myfinsight.report.evidence import (
    SELECTION_DISPLAY_NAMES,
    WEIGHTING_DISPLAY_NAMES,
)
from myfinsight.runtime.runlog import format_step_line
from myfinsight.schemas.market import DataQualityReport, UniverseResult
from myfinsight.schemas.profile import UserProfile
from myfinsight.schemas.report import AllocationRow, EvidenceItem, Report, ReportData
from myfinsight.schemas.results import BacktestResult, MetricsBundle, WeightSet
from myfinsight.schemas.runlog import StepRecord
from myfinsight.schemas.spec import StrategySpec

LIMIT_PAST_PERFORMANCE = (
    "Backtest 결과는 과거 데이터 기반 가상 성과이며 미래 수익을 보장하지 않습니다."
)
LIMIT_SURVIVORSHIP = "현재 지수 구성종목으로 과거를 계산하므로 생존·선견 편향이 있습니다."
LIMIT_INTERIM_CHANGES = "지수 정기 변경 사이의 수시 변경은 구성종목에 반영되지 않았습니다."
# 항상 붙는 고지 (요약 상단 알림 대상이 아님)
_STANDING_LIMITATIONS = frozenset(
    {LIMIT_PAST_PERFORMANCE, LIMIT_SURVIVORSHIP, LIMIT_INTERIM_CHANGES}
)

# 부록 B 섹션 번호 (프로토타입 필수 10개)
REQUIRED_SECTIONS: tuple[str, ...] = (
    "## 1. 요약",
    "## 2. 투자조건",
    "## 3. Portfolio 구성",
    "## 4. 전략 규칙",
    "## 5. 구성 근거",
    "## 7. Backtest 성과",
    "## 8. Risk",
    "## 10. 계산 조건",
    "## 11. 한계·주의",
    "## 12. 분석 과정 요약",
)

_PERF_ROWS: tuple[tuple[str, str], ...] = (
    ("누적수익률", "total_return"),
    ("CAGR", "cagr"),
)
_RISK_ROWS: tuple[tuple[str, str], ...] = (
    ("연환산 변동성", "ann_volatility"),
    ("Sharpe", "sharpe"),
    ("MDD", "mdd"),
)


def last_regular_change_date(today: date) -> date:
    """오늘 이전(포함) 가장 최근 지수 정기 변경일 (3·6·9·12월 셋째 금요일)."""
    year, month = today.year, today.month
    for _ in range(5):
        if month in (3, 6, 9, 12):
            first = date(year, month, 1)
            offset = (4 - first.weekday()) % 7  # 금요일 = 4
            third_friday = first + timedelta(days=offset + 14)
            if third_friday <= today:
                return third_friday
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    raise AssertionError("unreachable")  # pragma: no cover


def build_allocation(
    weights: WeightSet, backtest: BacktestResult, names: Mapping[str, str] | None = None
) -> list[AllocationRow]:
    """기준일 비중 × 초기자본으로 배분표를 만든다 (비중 내림차순, 동률은 티커 오름차순)."""
    names = names or {}
    cond = backtest.conditions
    rows = []
    for ticker, w in sorted(weights.weights.items(), key=lambda kv: (-kv[1], kv[0])):
        if w <= 0:
            continue
        amount_usd = w * cond.initial_capital_usd
        rows.append(AllocationRow(
            ticker=ticker, name=names.get(ticker), weight=w, amount_usd=amount_usd,
            amount_krw=krw_amount(amount_usd, cond.fx_rate_krw_per_usd),
        ))
    return rows


def build_limitations(
    *,
    spec: StrategySpec,
    universe: UniverseResult,
    quality: DataQualityReport,
    today: date,
    extra: Iterable[str] = (),
) -> list[str]:
    """한계 목록: 고정 2개 + 조건부 항목 (데이터 부족 제외, 스냅샷 노후, 수시 변경 미반영)."""
    items = [LIMIT_PAST_PERFORMANCE, LIMIT_SURVIVORSHIP]
    if quality.excluded:
        excluded = ", ".join(f"{t}({quality.excluded[t]})" for t in sorted(quality.excluded))
        items.append(f"데이터 부족으로 제외된 종목: {excluded}")
    if spec.universe.mode == "dynamic":
        if universe.snapshot_dates:
            oldest = min(universe.snapshot_dates.values())
            regular = last_regular_change_date(today)
            if oldest < regular:
                items.append(
                    f"구성종목 스냅샷({fmt_date(oldest)})이 직전 정기 변경일"
                    f"({fmt_date(regular)})보다 오래되었습니다."
                )
        items.append(LIMIT_INTERIM_CHANGES)
    for text in extra:
        if text not in items:
            items.append(text)
    return items


def build_report_data(
    *,
    run_id: str,
    created_at: datetime,
    profile: UserProfile,
    spec: StrategySpec,
    weights: WeightSet,
    backtest: BacktestResult,
    metrics: MetricsBundle,
    evidence: list[EvidenceItem],
    universe: UniverseResult,
    quality: DataQualityReport,
    steps: list[StepRecord],
    names: Mapping[str, str] | None = None,
    extra_limitations: Iterable[str] = (),
) -> ReportData:
    """Report 구조 데이터를 만든다 (계산 없이 입력값을 옮겨 담는다)."""
    return ReportData(
        run_id=run_id,
        created_at=created_at,
        profile=profile,
        spec=spec,
        spec_hash=weights.spec_hash,
        allocation_as_of=weights.as_of,
        allocation=build_allocation(weights, backtest, names),
        metrics=metrics,
        conditions=backtest.conditions,
        evidence=evidence,
        limitations=build_limitations(
            spec=spec, universe=universe, quality=quality, today=created_at.date(),
            extra=extra_limitations,
        ),
        process_summary=steps,
    )


class _Renderer:
    """표시값을 기록하면서 Markdown을 만든다."""

    def __init__(self, data: ReportData) -> None:
        self.data = data
        self.values: dict[str, str] = {}
        self.lines: list[str] = []

    def v(self, path: str) -> str:
        text = format_path(self.data, path)
        self.values[path] = text
        return text

    def add(self, *lines: str) -> None:
        self.lines.extend(lines)

    # -- 섹션 ---------------------------------------------------------------
    def header(self) -> None:
        d = self.data
        self.add(
            f"# MyFinSight 분석 Report — {d.spec.name}",
            "",
            f"- 실행 ID: `{d.run_id}`",
            f"- 작성 시각(UTC): {d.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        )

    def summary(self) -> None:
        d = self.data
        m = d.metrics
        n = len(d.allocation)
        conditional = [t for t in d.limitations if t not in _STANDING_LIMITATIONS]
        self.add("## 1. 요약", "")
        if conditional:
            self.add(
                f"> ⚠ 제외·한계 사항 {len(conditional)}건이 있습니다 (11. 한계·주의 참고).", ""
            )
        tickers = ", ".join(r.ticker for r in d.allocation)
        self.add(
            f"- Portfolio: {n}개 종목 ({tickers}), 기준일 {self.v('allocation_as_of')}",
            f"- Backtest {self.v('conditions.start')} ~ {self.v('conditions.end')}: "
            f"누적수익률 {self.v('metrics.strategy.total_return')}, "
            f"CAGR {self.v('metrics.strategy.cagr')}, "
            f"MDD {self.v('metrics.strategy.mdd')}",
            f"- Benchmark({d.conditions.benchmark}) 대비 초과 누적수익률 "
            f"{self.v('metrics.excess_total_return')}, 초과 CAGR {self.v('metrics.excess_cagr')}",
        )
        vol_cmp = (
            "낮고" if m.strategy.ann_volatility < m.benchmark.ann_volatility
            else "높거나 같고"
        )
        within = -m.strategy.mdd * 100 <= d.profile.loss_tolerance_pct
        mdd_cmp = "이내입니다" if within else "를 초과합니다"
        self.add(
            f"- 결과 해석(템플릿): 이 Portfolio의 연환산 변동성은 Benchmark보다 {vol_cmp}, "
            f"최대낙폭은 손실 감내 수준(-{self.v('profile.loss_tolerance_pct')}) {mdd_cmp}.",
            "",
        )

    def conditions_of_profile(self) -> None:
        p = self.data.profile
        c = p.constraints
        risk = p.risk_type.value
        if p.risk_type != p.risk_type_computed:
            risk += f" (산출: {p.risk_type_computed.value}, 사용자 변경)"
        per_ticker = ", ".join(
            f"{t} {self.v(f'profile.constraints.max_weight_per_ticker.{t}')}"
            for t in sorted(c.max_weight_per_ticker)
        ) or "없음"
        self.add(
            "## 2. 투자조건", "",
            "| 항목 | 값 |", "|---|---|",
            f"| Profile ID | {p.profile_id} |",
            f"| 투자금 | {self.v('profile.investment_amount_krw')} |",
            f"| 투자기간 | {p.horizon_months}개월 |",
            f"| 투자성향 | {risk} |",
            f"| 손실 감내 수준 | -{self.v('profile.loss_tolerance_pct')} |",
            f"| 관심산업 | {', '.join(p.interest_industries) or '없음'} |",
            f"| 선호조건 | {', '.join(p.preferences) or '없음'} |",
            f"| 제외 종목 | {', '.join(c.exclude_tickers) or '없음'} |",
            f"| 전체 공통 최대 비중 | {self.v('profile.constraints.max_weight_all')} |",
            f"| 종목별 최대 비중 | {per_ticker} |",
            f"| ETF 허용 | {'예' if c.allow_etf else '아니오'} |",
            f"| 투자 시장 | {p.market} |",
            "",
            "- 이번 분석에서 바꾼 값: 없음 (프로토타입은 고정 Profile 사용)",
            "",
        )

    def portfolio(self) -> None:
        d = self.data
        self.add(
            "## 3. Portfolio 구성", "",
            f"- 기준일: {self.v('allocation_as_of')}",
            f"- 초기자본: {self.v('profile.investment_amount_krw')} = "
            f"{self.v('conditions.initial_capital_usd')}",
            f"- 적용 환율: {self.v('conditions.fx_rate_krw_per_usd')} KRW/USD "
            f"({self.v('conditions.fx_as_of')} 기준)",
            "",
            "| 종목 | 종목명 | 비중 | 금액(USD) | 금액(원) |",
            "|---|---|---:|---:|---:|",
        )
        for r in d.allocation:
            base = f"allocation.{r.ticker}"
            self.add(
                f"| {r.ticker} | {r.name or '-'} | {self.v(base + '.weight')} | "
                f"{self.v(base + '.amount_usd')} | {self.v(base + '.amount_krw')} |"
            )
        self.add(
            f"| 합계 | | {self.v('total.weight')} | {self.v('total.amount_usd')} | "
            f"{self.v('total.amount_krw')} |",
            "",
        )

    def strategy_rules(self) -> None:
        s = self.data.spec
        c = s.constraints
        universe = (
            "동적 (지수 구성종목 + 관심산업 필터)" if s.universe.mode == "dynamic"
            else f"고정 목록 ({', '.join(s.universe.tickers)})"
        )
        per_ticker = ", ".join(
            f"{t} {self.v(f'spec.constraints.max_weight_per_ticker.{t}')}"
            for t in sorted(c.max_weight_per_ticker)
        ) or "없음"
        self.add(
            "## 4. 전략 규칙", "",
            f"- 전략: {s.name} (`{s.spec_id}` v{s.version}, "
            f"Spec 해시 `{self.data.spec_hash[:12]}`)",
            f"- Universe: {universe}",
            f"- 선정 규칙: {SELECTION_DISPLAY_NAMES[s.selection.rule]} "
            f"(`{s.selection.rule.value}`, {_params(s.selection.params)})",
            f"- 비중 규칙: {WEIGHTING_DISPLAY_NAMES[s.weighting.rule]} "
            f"(`{s.weighting.rule.value}`, {_params(s.weighting.params)})",
            f"- 제약: 제외 종목 {', '.join(c.exclude_tickers) or '없음'} / "
            f"전체 상한 {self.v('spec.constraints.max_weight_all')} / 종목별 상한 {per_ticker}",
            f"- 리밸런싱: 분기({s.rebalance}) 첫 거래일, 기간 {s.period_years}년, "
            f"Benchmark {s.benchmark}",
            "",
        )

    def rationale(self) -> None:
        ev = self.data.evidence
        self.add("## 5. 구성 근거", "")
        for item in (e for e in ev if e.kind == "universe"):
            self.add(f"- {item.statement} {_cite(item)}")
        self.add("")
        for row in self.data.allocation:
            items = [e for e in ev if e.subject == row.ticker
                     and e.kind in ("selection", "weight", "cap")]
            label = f"**{row.ticker}**" + (f" ({row.name})" if row.name else "")
            self.add(f"- {label}")
            for item in items:
                self.add(f"  - {item.statement} {_cite(item)}")
        self.add("")

    def performance(self) -> None:
        bm = self.data.conditions.benchmark
        self.add(
            "## 7. Backtest 성과", "",
            f"기간: {self.v('conditions.start')} ~ {self.v('conditions.end')}",
            "",
            f"| 지표 | 전략 | Benchmark ({bm}) |", "|---|---:|---:|",
        )
        for label, field in _PERF_ROWS:
            self.add(
                f"| {label} | {self.v(f'metrics.strategy.{field}')} | "
                f"{self.v(f'metrics.benchmark.{field}')} |"
            )
        self.add(
            f"| 초과 누적수익률 | {self.v('metrics.excess_total_return')} | - |",
            f"| 초과 CAGR | {self.v('metrics.excess_cagr')} | - |",
            "",
        )

    def risk(self) -> None:
        bm = self.data.conditions.benchmark
        self.add("## 8. Risk", "", f"| 지표 | 전략 | Benchmark ({bm}) |", "|---|---:|---:|")
        for label, field in _RISK_ROWS:
            self.add(
                f"| {label} | {self.v(f'metrics.strategy.{field}')} | "
                f"{self.v(f'metrics.benchmark.{field}')} |"
            )
        self.add(
            f"| MDD 구간 | {self.v('metrics.strategy.mdd_peak')} ~ "
            f"{self.v('metrics.strategy.mdd_trough')} | "
            f"{self.v('metrics.benchmark.mdd_peak')} ~ {self.v('metrics.benchmark.mdd_trough')} |",
            "",
        )
        for item in (e for e in self.data.evidence if e.kind == "metric"):
            self.add(f"- {item.statement} {_cite(item)}")
        self.add("")

    def calc_conditions(self) -> None:
        c = self.data.conditions
        self.add(
            "## 10. 계산 조건", "",
            f"- 기간: {self.v('conditions.start')} ~ {self.v('conditions.end')}",
            f"- 리밸런싱: {c.rebalance} (분기 첫 거래일 종가 체결)",
            f"- Benchmark: {c.benchmark}",
            f"- 거래비용: {self.v('conditions.cost_bps')}",
            f"- 무위험수익률(연): {self.v('conditions.risk_free_annual')}",
            f"- 기준 통화: {c.base_currency}",
            f"- 초기자본: {self.v('conditions.initial_capital_usd')}",
            f"- 환율: {self.v('conditions.fx_rate_krw_per_usd')} KRW/USD "
            f"({self.v('conditions.fx_as_of')} 기준, 표시용)",
            "",
        )

    def limitations(self) -> None:
        self.add("## 11. 한계·주의", "")
        for text in self.data.limitations:
            self.add(f"- {text}")
        for item in (e for e in self.data.evidence if e.kind == "limitation"):
            self.add(f"- {item.statement} {_cite(item)}")
        self.add("")

    def process(self) -> None:
        self.add("## 12. 분석 과정 요약", "")
        for rec in self.data.process_summary:
            self.add(f"- {format_step_line(rec)}")
        self.add("")

    def render(self) -> str:
        self.header()
        self.summary()
        self.conditions_of_profile()
        self.portfolio()
        self.strategy_rules()
        self.rationale()
        self.performance()
        self.risk()
        self.calc_conditions()
        self.limitations()
        self.process()
        return "\n".join(self.lines).rstrip() + "\n"


def _params(params: Mapping[str, object]) -> str:
    if not params:
        return "파라미터 없음"
    return ", ".join(f"{k}={json.dumps(params[k], ensure_ascii=False)}" for k in sorted(params))


def _cite(item: EvidenceItem) -> str:
    return f"_(출처: {item.source}, 기준일: {fmt_date(item.as_of)})_"


def render_markdown(data: ReportData) -> tuple[str, dict[str, str]]:
    """ReportData를 Markdown으로 렌더링하고 (텍스트, 표시값 목록)을 돌려준다."""
    renderer = _Renderer(data)
    text = renderer.render()
    return text, renderer.values


def assemble_report(
    *,
    run_id: str,
    created_at: datetime,
    profile: UserProfile,
    spec: StrategySpec,
    weights: WeightSet,
    backtest: BacktestResult,
    metrics: MetricsBundle,
    evidence: list[EvidenceItem],
    universe: UniverseResult,
    quality: DataQualityReport,
    steps: list[StepRecord],
    names: Mapping[str, str] | None = None,
    extra_limitations: Iterable[str] = (),
) -> Report:
    """ReportData 생성 → 렌더링 → Report 반환 (저장하지 않음)."""
    data = build_report_data(
        run_id=run_id, created_at=created_at, profile=profile, spec=spec, weights=weights,
        backtest=backtest, metrics=metrics, evidence=evidence, universe=universe,
        quality=quality, steps=steps, names=names, extra_limitations=extra_limitations,
    )
    text, values = render_markdown(data)
    return Report(data=data, text_markdown=text, display_values=values)
