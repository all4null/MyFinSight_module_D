"""M00-02 시장 데이터 스키마 (M02-xx, M03-05)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from myfinsight.schemas.base import SchemaModel
from myfinsight.schemas.enums import DataStatus, IndexCode


class RawPriceBatch(SchemaModel):
    """M02-01 출력: 원본 응답 보존."""

    source: str
    requested_tickers: list[str]
    start: date
    end: date
    fetched_at: datetime
    payload: dict[str, Any]
    failed_tickers: dict[str, str] = {}


class PriceBar(SchemaModel):
    """M02-02 출력 행 (수정종가)."""

    ticker: str
    date: date
    adj_close: float = Field(gt=0)
    volume: int | None = Field(None, ge=0)
    currency: Literal["USD"] = "USD"
    source: str
    fetched_at: datetime


class FxRate(SchemaModel):
    """환율 (USD/KRW)."""

    pair: Literal["USDKRW"] = "USDKRW"
    date: date
    rate: float = Field(gt=0)
    source: str
    fetched_at: datetime


class PriceMeta(SchemaModel):
    """PriceFrame과 함께 전달되는 메타."""

    source: str
    as_of: date
    fetched_at: datetime
    tickers: list[str]


class TickerQuality(SchemaModel):
    """티커별 데이터 품질 판정."""

    ticker: str
    coverage: float
    filled_days: int
    status: DataStatus
    reason: str | None = None
    is_required: bool


class DataQualityReport(SchemaModel):
    """M02-03 출력."""

    as_of: date
    expected_days: int
    items: list[TickerQuality]
    usable_tickers: list[str]
    excluded: dict[str, str]


class IndexConstituent(SchemaModel):
    """M02-05 출력: 지수 구성종목 한 행."""

    index_code: IndexCode
    ticker: str
    name: str
    sector: str
    industry: str
    snapshot_date: date
    source: str
    fetched_at: datetime


class UniverseResult(SchemaModel):
    """M03-05 출력."""

    tickers: list[str]
    snapshot_dates: dict[IndexCode, date]
    criteria: dict[str, Any]
    excluded: dict[str, str]
    source: str
