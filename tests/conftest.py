"""공통 테스트 시나리오: 부록 A 예시 Profile·Spec + 손계산 가능한 전략·Backtest 결과."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from myfinsight.schemas import (
    BacktestResult,
    CalcConditions,
    DataQualityReport,
    DataStatus,
    IndexCode,
    IndexConstituent,
    MetricsBundle,
    PerformanceMetrics,
    PriceMeta,
    RebalanceRecord,
    StepRecord,
    StrategySpec,
    TickerQuality,
    TickerSignal,
    UniverseResult,
    UserProfile,
    ValidationResult,
    WeightSet,
)
from myfinsight.schemas.results import METRIC_VOLATILITY

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "inputs" / "profile.json"
SPEC_PATH = ROOT / "inputs" / "spec.json"

FETCHED_AT = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
AS_OF = date(2026, 10, 5)
DATA_AS_OF = date(2026, 10, 2)
FX = 1380.5

# 선정 5종목: 상한 전 비중 → 상한(전체 0.25, NVDA 0.15) 적용 후 비중 (M03-03 재분배 손계산)
PRE_CAP = {"NVDA": 0.30, "AAPL": 0.25, "MSFT": 0.20, "AVGO": 0.15, "ORCL": 0.10}
FINAL = {"NVDA": 0.15, "AAPL": 0.25, "MSFT": 0.25, "AVGO": 0.21, "ORCL": 0.14}
VOLS = {"MSFT": 0.21, "AAPL": 0.22, "ORCL": 0.235, "AVGO": 0.26, "NVDA": 0.31}
NAMES = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "NVDA": "NVIDIA Corp.",
    "AVGO": "Broadcom Inc.", "ORCL": "Oracle Corp.",
}


@dataclass
class Scenario:
    profile: UserProfile
    spec: StrategySpec
    universe: UniverseResult
    quality: DataQualityReport
    price_meta: PriceMeta
    weights: WeightSet
    backtest: BacktestResult
    metrics: MetricsBundle
    constituents: dict[IndexCode, list[IndexConstituent]]
    steps: list[StepRecord] = field(default_factory=list)


def _perf(total: float, cagr: float, vol: float, sharpe: float | None, mdd: float):
    return PerformanceMetrics(
        total_return=total, cagr=cagr, ann_volatility=vol, sharpe=sharpe, mdd=mdd,
        mdd_peak=date(2021, 12, 27), mdd_trough=date(2022, 10, 12),
    )


def make_scenario() -> Scenario:
    profile = UserProfile.model_validate_json(PROFILE_PATH.read_text(encoding="utf-8"))
    spec = StrategySpec.model_validate_json(SPEC_PATH.read_text(encoding="utf-8"))
    h = spec.spec_hash()
    candidates = sorted(VOLS) + [f"C{i:02d}" for i in range(15)]
    universe = UniverseResult(
        tickers=candidates,
        snapshot_dates={IndexCode.SP500: date(2026, 9, 21), IndexCode.NDX: date(2026, 9, 21)},
        criteria={"industries": profile.interest_industries, "max_size": 60},
        excluded={}, source="fake-constituents",
    )
    items = [
        TickerQuality(ticker=t, coverage=1.0, filled_days=0, status=DataStatus.OK,
                      is_required=False)
        for t in candidates
    ]
    items.append(TickerQuality(ticker="C99", coverage=0.9, filled_days=0,
                               status=DataStatus.EXCLUDED, reason="커버리지 0.9000 < 0.95",
                               is_required=False))
    quality = DataQualityReport(
        as_of=DATA_AS_OF, expected_days=1512, items=items,
        usable_tickers=candidates, excluded={"C99": "커버리지 0.9000 < 0.95"},
    )
    price_meta = PriceMeta(source="yfinance", as_of=DATA_AS_OF, fetched_at=FETCHED_AT,
                           tickers=candidates + ["SPY"])
    ranked = sorted(VOLS, key=lambda t: (VOLS[t], t))
    signals = [
        TickerSignal(ticker=t, metric_name=METRIC_VOLATILITY, value=VOLS[t],
                     rank=ranked.index(t) + 1, universe_size=len(candidates))
        for t in sorted(VOLS)
    ]
    weights = WeightSet(as_of=AS_OF, spec_hash=h, weights=dict(FINAL),
                        pre_cap_weights=dict(PRE_CAP), signals=signals, selected=sorted(FINAL))
    capital = profile.investment_amount_krw / FX
    conditions = CalcConditions(
        start=date(2021, 10, 1), end=DATA_AS_OF, rebalance="Q", benchmark="SPY", cost_bps=10.0,
        risk_free_annual=0.0, initial_capital_usd=capital, fx_rate_krw_per_usd=FX,
        fx_as_of=DATA_AS_OF,
    )
    backtest = BacktestResult(
        conditions=conditions, spec_hash=h,
        equity_curve={date(2021, 10, 1): capital, DATA_AS_OF: capital * 1.8123},
        benchmark_curve={date(2021, 10, 1): capital, DATA_AS_OF: capital * 1.6},
        rebalances=[RebalanceRecord(date=date(2021, 10, 1), weights=dict(FINAL), turnover=1.0,
                                    cost_usd=capital * 0.001)],
    )
    metrics = MetricsBundle(
        strategy=_perf(0.8123, 0.1263, 0.1987, 0.6421, -0.2245),
        benchmark=_perf(0.6, 0.0986, 0.1712, 0.5843, -0.2450),
        excess_total_return=0.8123 - 0.6, excess_cagr=0.1263 - 0.0986,
    )
    constituents = {
        IndexCode.SP500: [
            IndexConstituent(index_code=IndexCode.SP500, ticker=t, name=NAMES.get(t, t),
                             sector="Information Technology", industry="Software",
                             snapshot_date=date(2026, 9, 21), source="fake-constituents",
                             fetched_at=FETCHED_AT)
            for t in candidates
        ]
    }
    return Scenario(profile, spec, universe, quality, price_meta, weights, backtest, metrics,
                    constituents)


@pytest.fixture
def scenario() -> Scenario:
    return make_scenario()


class FakeRepo:
    """M02-04 Repository 인메모리 Fake."""

    def __init__(self) -> None:
        self.steps: dict[tuple[str, str], StepRecord] = {}
        self.artifacts: dict[str, dict] = {}
        self.reports: dict = {}
        self.fail_save_step = False

    def save_step(self, rec: StepRecord) -> None:
        if self.fail_save_step:
            raise RuntimeError("disk full")
        self.steps[(rec.run_id, rec.step)] = rec

    def get_steps(self, run_id: str) -> list[StepRecord]:
        return [r for (rid, _), r in self.steps.items() if rid == run_id]

    def save_run_artifact(self, run_id, profile, spec, universe, config) -> None:
        self.artifacts[run_id] = {"profile": profile, "spec": spec, "universe": universe,
                                  "config": config}

    def save_report(self, report) -> None:
        self.reports[report.data.run_id] = report


class FakePorts:
    """묶음 A·B·C 모듈 Fake. ``fail`` 에 단계 메서드 이름 → 예외를 넣으면 그 호출이 실패한다."""

    def __init__(self, sc: Scenario | None = None) -> None:
        self.sc = sc or make_scenario()
        self.repo = FakeRepo()
        self.fail: dict[str, Exception] = {}
        self.spec_result = ValidationResult(ok=True)
        self.weight_result = ValidationResult(ok=True)
        self.constituent_warnings: list[str] = []
        self.calls: list[str] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def load_config(self, path):
        self._call("load_config")
        return {"config_path": str(path)}

    def open_repository(self, config):
        self._call("open_repository")
        return self.repo

    def load_profile(self, path, config, repo):
        self._call("load_profile")
        return UserProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def load_spec(self, path):
        self._call("load_spec")
        from myfinsight.runtime.pipeline import load_spec_file

        return load_spec_file(Path(path))

    def validate_spec(self, spec, profile, config):
        self._call("validate_spec")
        return self.spec_result

    def ensure_constituents(self, repo, config, today, force):
        self._call("ensure_constituents")
        return self.sc.constituents, list(self.constituent_warnings)

    def build_universe(self, constituents, profile, spec, config):
        self._call("build_universe")
        return self.sc.universe

    def fetch_prices(self, repo, tickers, spec, config, today):
        self._call("fetch_prices")
        return "PRICES", self.sc.price_meta

    def assess_quality(self, prices, spec, config):
        self._call("assess_quality")
        return self.sc.quality, "CLEAN_PRICES"

    def compute_weights(self, spec, universe, prices, as_of):
        self._call("compute_weights")
        return self.sc.weights.model_copy(update={"spec_hash": spec.spec_hash()})

    def validate_weights(self, weights, spec, universe):
        self._call("validate_weights")
        return self.weight_result

    def run_backtest(self, spec, universe, prices, profile, config, repo):
        self._call("run_backtest")
        return self.sc.backtest.model_copy(update={"spec_hash": spec.spec_hash()})

    def compute_metrics(self, backtest, config):
        self._call("compute_metrics")
        return self.sc.metrics


@pytest.fixture
def fake_ports() -> FakePorts:
    return FakePorts()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
