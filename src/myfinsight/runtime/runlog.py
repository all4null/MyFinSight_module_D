"""M08-01 실행 기록기 (Run Logger) — FR24, R9.

단계마다 STARTED → SUCCESS/PARTIAL/FAILED 기록을 저장소(M02-04)에 남긴다.
기록만 하고 흐름은 제어하지 않는다: 예외는 FAILED로 기록한 뒤 그대로 다시 던지며,
기록 저장 실패는 logging 경고만 남기고 분석을 실패시키지 않는다. 시각은 UTC.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from myfinsight.schemas.enums import StepStatus
from myfinsight.schemas.errors import MyFinSightError
from myfinsight.schemas.runlog import StepRecord

logger = logging.getLogger(__name__)

# 단계 이름 표준 (실행 순서) → 사용자 표시 라벨
STEP_LABELS: dict[str, str] = {
    "load_profile": "Profile 불러오기",
    "validate_spec": "Spec 검증",
    "constituents": "구성종목 확인",
    "universe": "Universe 구성",
    "fetch_prices": "데이터 조회",
    "data_quality": "데이터 품질 판정",
    "compute_weights": "기준일 비중 산출",
    "validate_weights": "비중 검증",
    "backtest": "Backtest",
    "metrics": "성과 지표 계산",
    "evidence": "근거 생성",
    "report": "Report 생성",
    "consistency": "일치성 검사",
}
STANDARD_STEPS: tuple[str, ...] = tuple(STEP_LABELS)

STATUS_LABELS: dict[StepStatus, str] = {
    StepStatus.STARTED: "진행 중",
    StepStatus.SUCCESS: "성공",
    StepStatus.PARTIAL: "부분 성공",
    StepStatus.FAILED: "실패",
    StepStatus.SKIPPED: "생략",
}

UNEXPECTED_ERROR_CODE = "UNEXPECTED_ERROR"


class StepStore(Protocol):
    """RunLogger가 쓰는 저장소 기능 (M02-04 MarketDataRepository의 부분집합)."""

    def save_step(self, rec: StepRecord) -> None:
        """단계 기록을 저장(같은 run_id·step이면 갱신)한다."""
        ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def format_step_line(rec: StepRecord) -> str:
    """Report 12번 섹션용 한 줄. 예: ``데이터 조회: 성공 (52/55, 3개 제외)``."""
    label = STEP_LABELS.get(rec.step, rec.step)
    line = f"{label}: {STATUS_LABELS[rec.status]}"
    detail = rec.summary
    if rec.status == StepStatus.FAILED and rec.error_code:
        detail = f"{rec.error_code}: {rec.error_message or ''}".rstrip(": ")
    if detail:
        line += f" ({detail})"
    if rec.sources:
        line += f" [출처: {', '.join(rec.sources)}]"
    return line


class StepHandle:
    """단계 진행 중 요약·출처·부분 성공 사유를 모은다."""

    def __init__(self) -> None:
        self.summary: str | None = None
        self.sources: list[str] = []
        self.partial_reason: str | None = None

    def set_summary(self, text: str) -> None:
        """단계 결과 요약을 기록한다."""
        self.summary = text

    def add_source(self, name: str) -> None:
        """사용한 데이터 출처를 추가한다 (중복 무시)."""
        if name not in self.sources:
            self.sources.append(name)

    def mark_partial(self, reason: str) -> None:
        """단계를 PARTIAL로 끝내도록 표시한다."""
        self.partial_reason = reason


class RunLogger:
    """분석 1건(run_id)의 단계 기록기."""

    def __init__(
        self,
        run_id: str,
        repo: StepStore,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.run_id = run_id
        self._repo = repo
        self._clock = clock
        self._records: dict[str, StepRecord] = {}

    def _save(self, rec: StepRecord) -> None:
        self._records[rec.step] = rec
        try:
            self._repo.save_step(rec)
        except Exception:  # noqa: BLE001 - 기록 실패가 분석을 실패시키지 않는다
            logger.warning("실행 기록 저장 실패: run_id=%s step=%s", self.run_id, rec.step,
                           exc_info=True)

    @contextmanager
    def step(self, name: str) -> Iterator[StepHandle]:
        """단계를 감싼다. 진입 시 STARTED, 정상 종료 시 SUCCESS(또는 PARTIAL), 예외 시 FAILED."""
        started = self._clock()
        self._save(StepRecord(run_id=self.run_id, step=name, status=StepStatus.STARTED,
                              started_at=started))
        handle = StepHandle()
        try:
            yield handle
        except BaseException as exc:
            code = exc.code if isinstance(exc, MyFinSightError) else UNEXPECTED_ERROR_CODE
            message = exc.message if isinstance(exc, MyFinSightError) else repr(exc)
            self._save(StepRecord(
                run_id=self.run_id, step=name, status=StepStatus.FAILED, started_at=started,
                ended_at=self._clock(), summary=handle.summary, sources=list(handle.sources),
                error_code=code, error_message=message,
            ))
            raise
        status = StepStatus.PARTIAL if handle.partial_reason else StepStatus.SUCCESS
        summary = handle.summary
        if handle.partial_reason:
            summary = f"{summary}; {handle.partial_reason}" if summary else handle.partial_reason
        self._save(StepRecord(
            run_id=self.run_id, step=name, status=status, started_at=started,
            ended_at=self._clock(), summary=summary, sources=list(handle.sources),
        ))

    def skip(self, name: str, reason: str) -> None:
        """실행하지 않은 단계를 SKIPPED로 기록한다."""
        now = self._clock()
        self._save(StepRecord(run_id=self.run_id, step=name, status=StepStatus.SKIPPED,
                              started_at=now, ended_at=now, summary=reason))

    def records(self) -> list[StepRecord]:
        """단계별 최신 기록 (실행 순서)."""
        return list(self._records.values())

    def summary_lines(self) -> list[str]:
        """Report 12번 섹션용 요약 문자열 목록."""
        return [format_step_line(r) for r in self.records()]
