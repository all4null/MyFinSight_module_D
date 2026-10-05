"""실제 모듈 연결 (묶음 A·B·C 공개 API → PipelinePorts).

각 묶음 모듈이 아래 "합의 API"로 공개 함수를 제공하면 그대로 연결된다
(docs/INTEGRATION.md). 아직 없는 모듈을 호출하면 ``ConfigError(CONFIG_MODULE_MISSING)`` 로
어느 모듈이 빠졌는지 알린다. 이 파일은 호출 연결만 하며 계산을 하지 않는다.
"""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from myfinsight.runtime.pipeline import load_spec_file
from myfinsight.runtime.ports import AppConfig, Constituents, RunRepository
from myfinsight.schemas.errors import ConfigError
from myfinsight.schemas.market import DataQualityReport, PriceMeta, UniverseResult
from myfinsight.schemas.profile import UserProfile
from myfinsight.schemas.results import BacktestResult, MetricsBundle, ValidationResult, WeightSet
from myfinsight.schemas.spec import StrategySpec

if TYPE_CHECKING:
    import pandas as pd


def _api(module: str, name: str) -> Any:
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError) as exc:
        raise ConfigError(
            f"연결할 모듈 API가 없습니다: {module}.{name}",
            code="CONFIG_MODULE_MISSING",
            details={"module": module, "name": name},
        ) from exc


class DefaultPorts:
    """``myfinsight.*`` 실제 모듈을 호출하는 PipelinePorts 구현."""

    def load_config(self, path: Path) -> AppConfig:
        """M00-01."""
        return _api("myfinsight.config", "load_config")(path)

    def open_repository(self, config: AppConfig) -> RunRepository:
        """M02-04."""
        return _api("myfinsight.data.repository", "SqliteRepository")(config.data.db_url)

    def load_profile(self, path: Path, config: AppConfig, repo: RunRepository) -> UserProfile:
        """M01-01."""
        return _api("myfinsight.profile", "load_profile")(path, config, repo)

    def load_spec(self, path: Path) -> StrategySpec:
        """Spec 파일 로드 (M00-02 스키마)."""
        return load_spec_file(path)

    def validate_spec(
        self, spec: StrategySpec, profile: UserProfile, config: AppConfig
    ) -> ValidationResult:
        """M04-01."""
        return _api("myfinsight.validation.spec_validator", "validate_spec")(spec, profile, config)

    def ensure_constituents(
        self, repo: RunRepository, config: AppConfig, today: date, force: bool
    ) -> tuple[Constituents, list[str]]:
        """M02-05."""
        fn = _api("myfinsight.data.constituents", "ensure_constituents")
        return fn(repo, config, today, force)

    def build_universe(
        self, constituents: Constituents, profile: UserProfile, spec: StrategySpec,
        config: AppConfig,
    ) -> UniverseResult:
        """M03-05."""
        return _api("myfinsight.strategy.universe", "build_universe")(
            constituents, profile, spec, config
        )

    def fetch_prices(
        self, repo: RunRepository, tickers: list[str], spec: StrategySpec,
        config: AppConfig, today: date,
    ) -> tuple[pd.DataFrame, PriceMeta]:
        """M02-01·02·04."""
        return _api("myfinsight.data", "load_prices")(repo, tickers, spec, config, today)

    def assess_quality(
        self, prices: pd.DataFrame, spec: StrategySpec, config: AppConfig
    ) -> tuple[DataQualityReport, pd.DataFrame]:
        """M02-03."""
        return _api("myfinsight.data.quality", "assess_quality")(prices, spec, config)

    def compute_weights(
        self, spec: StrategySpec, universe: list[str], prices: pd.DataFrame, as_of: date
    ) -> WeightSet:
        """M03-04."""
        return _api("myfinsight.strategy.executor", "compute_weights")(
            spec, universe, prices, as_of
        )

    def validate_weights(
        self, weights: WeightSet, spec: StrategySpec, universe: list[str]
    ) -> ValidationResult:
        """M04-02."""
        return _api("myfinsight.validation.weight_validator", "validate_weights")(
            weights, spec, universe
        )

    def run_backtest(
        self, spec: StrategySpec, universe: list[str], prices: pd.DataFrame,
        profile: UserProfile, config: AppConfig, repo: RunRepository,
    ) -> BacktestResult:
        """M05-01 (+M05-03)."""
        return _api("myfinsight.backtest.simulator", "run_backtest")(
            spec, universe, prices, profile, config, repo
        )

    def compute_metrics(self, backtest: BacktestResult, config: AppConfig) -> MetricsBundle:
        """M05-02."""
        return _api("myfinsight.backtest.metrics", "compute_metrics")(backtest, config)
