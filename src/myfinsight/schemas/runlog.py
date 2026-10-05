"""M00-02 실행 기록 스키마 (M08-01)."""

from __future__ import annotations

from datetime import datetime

from myfinsight.schemas.base import SchemaModel
from myfinsight.schemas.enums import StepStatus


class StepRecord(SchemaModel):
    """실행 단계 한 건의 기록."""

    run_id: str
    step: str
    status: StepStatus
    started_at: datetime
    ended_at: datetime | None = None
    summary: str | None = None
    sources: list[str] = []
    error_code: str | None = None
    error_message: str | None = None
