"""M08-02가 호출하는 다른 묶음(A·B·C) 모듈의 공개 API 계약.

파이프라인은 이 Protocol에만 의존한다. 실제 모듈 연결은 :mod:`myfinsight.runtime.wiring`,
통합 테스트는 Fake 구현을 주입한다 (C-11 네트워크 격리).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from myfinsight.schemas.enums import IndexCode
from myfinsight.schemas.market import (
    DataQualityReport,
    IndexConstituent,
    PriceMeta,
    UniverseResult,
)
from myfinsight.schemas.profile import UserProfile
from myfinsight.schemas.report import Report
from myfinsight.schemas.results import (
    BacktestResult,
    MetricsBundle,
    ValidationResult,
    WeightSet,
)
from myfinsight.schemas.runlog import StepRecord
from myfinsight.schemas.spec import StrategySpec

if TYPE_CHECKING:
    import pandas as pd

# M00-01 AppConfig (묶음 C 소유). 파이프라인은 내용을 읽지 않고 그대로 전달만 한다.
AppConfig = Any
Constituents = dict[IndexCode, list[IndexConstituent]]


class RunRepository(Protocol):
    """M08이 쓰는 M02-04 MarketDataRepository 기능."""

    def save_step(self, rec: StepRecord) -> None:
        """단계 기록 저장."""
        ...

    def get_steps(self, run_id: str) -> list[StepRecord]:
        """실행 건의 단계 기록 조회."""
        ...

    def save_run_artifact(
        self, run_id: str, profile: UserProfile, spec: StrategySpec,
        universe: UniverseResult, config: AppConfig,
    ) -> None:
        """재현용 입력·Universe·설정 저장."""
        ...

    def save_report(self, report: Report) -> None:
        """Report 저장."""
        ...


class PipelinePorts(Protocol):
    """파이프라인 단계별 모듈 호출 (실행 흐름 0-2 순서)."""

    def load_config(self, path: Path) -> AppConfig:
        """M00-01 설정 로드. 실패 시 ConfigError."""
        ...

    def open_repository(self, config: AppConfig) -> RunRepository:
        """M02-04 저장소 열기. 실패 시 RepositoryError."""
        ...

    def load_profile(self, path: Path, config: AppConfig, repo: RunRepository) -> UserProfile:
        """M01-01 Profile 로드·검증. 실패 시 InputError(PROFILE_INVALID)."""
        ...

    def load_spec(self, path: Path) -> StrategySpec:
        """Spec 파일 로드·스키마 검증. 실패 시 InputError."""
        ...

    def validate_spec(
        self, spec: StrategySpec, profile: UserProfile, config: AppConfig
    ) -> ValidationResult:
        """M04-01 Spec 정적 검증."""
        ...

    def ensure_constituents(
        self, repo: RunRepository, config: AppConfig, today: date, force: bool
    ) -> tuple[Constituents, list[str]]:
        """M02-05 구성종목 확인(필요 시 갱신). (지수별 최신 구성종목, 경고 목록)."""
        ...

    def build_universe(
        self, constituents: Constituents, profile: UserProfile, spec: StrategySpec,
        config: AppConfig,
    ) -> UniverseResult:
        """M03-05 Universe 구성. 0개면 StrategyError(UNIVERSE_EMPTY)."""
        ...

    def fetch_prices(
        self, repo: RunRepository, tickers: list[str], spec: StrategySpec,
        config: AppConfig, today: date,
    ) -> tuple[pd.DataFrame, PriceMeta]:
        """M02-01·02·04 가격 수집(캐시 우선)·정규화·저장. tickers + Benchmark, 기간은 Spec 기준."""
        ...

    def assess_quality(
        self, prices: pd.DataFrame, spec: StrategySpec, config: AppConfig
    ) -> tuple[DataQualityReport, pd.DataFrame]:
        """M02-03 품질 판정. 필수 데이터 실패 시 DataQualityError."""
        ...

    def compute_weights(
        self, spec: StrategySpec, universe: list[str], prices: pd.DataFrame, as_of: date
    ) -> WeightSet:
        """M03-04 기준일 비중 산출."""
        ...

    def validate_weights(
        self, weights: WeightSet, spec: StrategySpec, universe: list[str]
    ) -> ValidationResult:
        """M04-02 비중 동적 검증."""
        ...

    def run_backtest(
        self, spec: StrategySpec, universe: list[str], prices: pd.DataFrame,
        profile: UserProfile, config: AppConfig, repo: RunRepository,
    ) -> BacktestResult:
        """M05-01(+M05-03) Backtest. 실패 시 BacktestError."""
        ...

    def compute_metrics(self, backtest: BacktestResult, config: AppConfig) -> MetricsBundle:
        """M05-02 성과 지표."""
        ...
