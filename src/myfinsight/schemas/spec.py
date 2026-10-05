"""M00-02 Strategy Spec 스키마 (FR08)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from myfinsight.schemas.base import SchemaModel
from myfinsight.schemas.enums import SelectionRule, WeightingRule


class SelectionSpec(SchemaModel):
    """종목 선정 규칙과 파라미터."""

    rule: SelectionRule
    params: dict[str, Any] = {}


class WeightingSpec(SchemaModel):
    """비중 결정 규칙과 파라미터."""

    rule: WeightingRule
    params: dict[str, Any] = {}


class ConstraintSpec(SchemaModel):
    """전략 제약조건."""

    exclude_tickers: list[str] = []
    max_weight_all: float = Field(1.0, gt=0, le=1.0)
    max_weight_per_ticker: dict[str, float] = {}


class UniverseSpec(SchemaModel):
    """후보 Universe 지정 방식 (dynamic: M03-05 / fixed: tickers 그대로)."""

    mode: Literal["dynamic", "fixed"] = "dynamic"
    tickers: list[str] = []


class StrategySpec(SchemaModel):
    """규칙 조합형 Strategy Spec."""

    spec_id: str
    name: str
    version: int = 1
    universe: UniverseSpec
    selection: SelectionSpec
    weighting: WeightingSpec
    constraints: ConstraintSpec
    rebalance: Literal["Q"] = "Q"
    period_years: int = Field(ge=1, le=20)
    benchmark: str

    def spec_hash(self) -> str:
        """정렬된 JSON의 SHA-256 (FR10 일치 확인용)."""
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
