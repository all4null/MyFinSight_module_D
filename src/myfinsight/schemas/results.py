"""M00-02 전략 실행·검증·Backtest 결과 스키마."""

from __future__ import annotations

from datetime import date

from myfinsight.schemas.base import SchemaModel

# TickerSignal.metric_name 표준값 (M03-01·M03-02가 채우고 M06-01이 읽는다)
METRIC_VOLATILITY = "ann_volatility"
METRIC_MOMENTUM = "momentum"


class TickerSignal(SchemaModel):
    """근거용 지표값 (M03-01/M03-02가 채움)."""

    ticker: str
    metric_name: str
    value: float
    rank: int | None = None
    universe_size: int


class WeightSet(SchemaModel):
    """M03-04 출력: 기준일 비중."""

    as_of: date
    spec_hash: str
    weights: dict[str, float]
    pre_cap_weights: dict[str, float]
    signals: list[TickerSignal]
    selected: list[str]


class ValidationIssue(SchemaModel):
    """검증 이슈 한 건."""

    code: str
    field: str | None = None
    message: str


class ValidationResult(SchemaModel):
    """검증 결과 (M04-01/M04-02/M04-03)."""

    ok: bool
    issues: list[ValidationIssue] = []


class CalcConditions(SchemaModel):
    """계산 조건 (FR12, Report 「계산 조건」)."""

    start: date
    end: date
    rebalance: str
    benchmark: str
    cost_bps: float
    risk_free_annual: float
    base_currency: str = "USD"
    initial_capital_usd: float
    fx_rate_krw_per_usd: float
    fx_as_of: date


class RebalanceRecord(SchemaModel):
    """리밸런싱 한 회 기록."""

    date: date
    weights: dict[str, float]
    turnover: float
    cost_usd: float


class BacktestResult(SchemaModel):
    """M05-01 출력."""

    conditions: CalcConditions
    spec_hash: str
    equity_curve: dict[date, float]
    benchmark_curve: dict[date, float]
    rebalances: list[RebalanceRecord]


class PerformanceMetrics(SchemaModel):
    """M05-02 출력 (비율은 소수: 0.152 = 15.2%). 계산 불가 지표는 None (METRIC_UNDEFINED)."""

    total_return: float
    cagr: float
    ann_volatility: float
    sharpe: float | None
    mdd: float
    mdd_peak: date
    mdd_trough: date


class MetricsBundle(SchemaModel):
    """전략·Benchmark 지표 묶음."""

    strategy: PerformanceMetrics
    benchmark: PerformanceMetrics
    excess_total_return: float
    excess_cagr: float
