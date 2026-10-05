"""M00-02 Enum 정의."""

from __future__ import annotations

from enum import Enum


class RiskType(str, Enum):
    """금융권 5단계 투자성향 (UC001)."""

    STABLE = "안정형"
    STABLE_SEEKING = "안정추구형"
    NEUTRAL = "위험중립형"
    ACTIVE = "적극투자형"
    AGGRESSIVE = "공격투자형"


class SelectionRule(str, Enum):
    """종목 선정 규칙 (M03-01)."""

    FIXED_LIST = "fixed_list"
    LOW_VOL_TOP_N = "low_volatility_top_n"
    MOMENTUM_TOP_N = "momentum_top_n"


class WeightingRule(str, Enum):
    """비중 결정 규칙 (M03-02)."""

    EQUAL = "equal"
    INVERSE_VOL = "inverse_volatility"


class StepStatus(str, Enum):
    """실행 단계 상태 (M08-01)."""

    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class DataStatus(str, Enum):
    """티커별 데이터 품질 판정 (M02-03)."""

    OK = "OK"
    FILLED = "FILLED"
    EXCLUDED = "EXCLUDED"


class IndexCode(str, Enum):
    """지원 지수."""

    SP500 = "SP500"
    NDX = "NDX"
