"""M00-02 근거·Report 스키마 (M06-01, M06-02)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from myfinsight.schemas.base import SchemaModel
from myfinsight.schemas.profile import UserProfile
from myfinsight.schemas.results import CalcConditions, MetricsBundle
from myfinsight.schemas.runlog import StepRecord
from myfinsight.schemas.spec import StrategySpec

EvidenceKind = Literal["universe", "selection", "weight", "cap", "metric", "limitation"]


class EvidenceItem(SchemaModel):
    """템플릿으로 만든 근거 문장 한 건."""

    subject: str
    kind: EvidenceKind
    statement: str
    values: dict[str, float | str]
    source: str
    as_of: date


class AllocationRow(SchemaModel):
    """배분표 한 행."""

    ticker: str
    name: str | None
    weight: float
    amount_usd: float
    amount_krw: int


class ReportData(SchemaModel):
    """M06-02가 텍스트로 렌더링하는 구조 데이터."""

    run_id: str
    created_at: datetime
    profile: UserProfile
    spec: StrategySpec
    spec_hash: str
    allocation_as_of: date
    allocation: list[AllocationRow]
    metrics: MetricsBundle
    conditions: CalcConditions
    evidence: list[EvidenceItem]
    limitations: list[str]
    process_summary: list[StepRecord]


class Report(SchemaModel):
    """렌더링된 Report."""

    data: ReportData
    text_markdown: str
    display_values: dict[str, str]
