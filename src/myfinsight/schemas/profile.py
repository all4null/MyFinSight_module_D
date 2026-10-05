"""M00-02 Profile 스키마 (UC001, 부록 A-1)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from myfinsight.schemas.base import SchemaModel
from myfinsight.schemas.enums import RiskType


class ProfileConstraints(SchemaModel):
    """사용자 투자 제약조건."""

    exclude_tickers: list[str] = []
    max_weight_all: float = Field(1.0, ge=0.05, le=1.0)
    max_weight_per_ticker: dict[str, float] = {}
    allow_etf: bool = False

    @field_validator("max_weight_per_ticker")
    @classmethod
    def _per_ticker_range(cls, v: dict[str, float]) -> dict[str, float]:
        for ticker, cap in v.items():
            if not 0.0 <= cap <= 1.0:
                raise ValueError(f"{ticker}: 종목별 상한은 0~1 범위여야 합니다 ({cap})")
        return v


class UserProfile(SchemaModel):
    """사용자 투자 Profile."""

    profile_id: str
    investment_amount_krw: int = Field(gt=0)
    horizon_months: int = Field(ge=12, le=120)
    risk_type_computed: RiskType
    risk_type: RiskType
    risk_type_overridden: bool
    loss_tolerance_pct: float = Field(gt=0, le=100)
    interest_industries: list[str] = []
    preferences: list[str] = []
    memo: str | None = None
    constraints: ProfileConstraints = ProfileConstraints()
    market: Literal["US"] = "US"
