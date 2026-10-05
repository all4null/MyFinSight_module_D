"""M00-02 공통 오류.

모든 실패는 ``MyFinSightError`` 하위 예외로 던지고 ``code`` 를 붙인다 (C-09).
코드 접두어는 명세 부록 C를 따른다.
"""

from __future__ import annotations

from typing import Any


class MyFinSightError(Exception):
    """MyFinSight 모든 예외의 기반 클래스."""

    code: str = "UNKNOWN"
    recoverable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigError(MyFinSightError):
    """설정 파일 누락·검증 실패 (CONFIG_)."""

    code = "CONFIG_INVALID"


class InputError(MyFinSightError):
    """Profile/Spec 입력 파일 오류 (PROFILE_, INPUT_)."""

    code = "INPUT_INVALID"


class DataSourceError(MyFinSightError):
    """외부 데이터 조회 실패 (DATA_)."""

    code = "DATA_SOURCE_UNAVAILABLE"


class DataQualityError(MyFinSightError):
    """필수 데이터 품질 기준 미달 (DATA_)."""

    code = "DATA_REQUIRED_MISSING"


class SpecValidationError(MyFinSightError):
    """Spec 정적 검증 실패 (SPEC_)."""

    code = "SPEC_INVALID"


class WeightValidationError(MyFinSightError):
    """비중 동적 검증 실패 (WEIGHT_)."""

    code = "WEIGHT_INVALID"


class StrategyError(MyFinSightError):
    """전략 규칙 실행 불가 (STRATEGY_, UNIVERSE_)."""

    code = "STRATEGY_FAILED"


class BacktestError(MyFinSightError):
    """Backtest·지표 계산 실패 (BACKTEST_, METRIC_)."""

    code = "BACKTEST_FAILED"


class ConsistencyError(MyFinSightError):
    """Report 수치 일치성 검사 실패 (CONSIST_)."""

    code = "CONSIST_FAILED"


class RepositoryError(MyFinSightError):
    """저장소 읽기·쓰기 실패 (REPO_)."""

    code = "REPO_WRITE_FAILED"
