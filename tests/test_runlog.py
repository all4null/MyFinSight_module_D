from datetime import UTC, datetime, timedelta

import pytest

from conftest import FakeRepo
from myfinsight.runtime.runlog import RunLogger, format_step_line
from myfinsight.schemas import DataQualityError, StepStatus


def clock():
    t = [datetime(2026, 10, 5, tzinfo=UTC)]

    def tick():
        t[0] += timedelta(seconds=1)
        return t[0]

    return tick


def test_success_partial_and_skip():
    repo = FakeRepo()
    log = RunLogger("r1", repo, clock=clock())
    with log.step("fetch_prices") as h:
        h.set_summary("55개 종목")
        h.add_source("yfinance")
        h.add_source("yfinance")
    with log.step("data_quality") as h:
        h.set_summary("52/55")
        h.mark_partial("3개 제외")
    log.skip("constituents", "고정 Universe Spec")
    recs = {r.step: r for r in log.records()}
    assert recs["fetch_prices"].status == StepStatus.SUCCESS
    assert recs["fetch_prices"].sources == ["yfinance"]
    assert recs["fetch_prices"].ended_at > recs["fetch_prices"].started_at
    assert recs["data_quality"].status == StepStatus.PARTIAL
    assert recs["constituents"].status == StepStatus.SKIPPED
    assert repo.get_steps("r1") == log.records()
    assert log.summary_lines()[0] == "데이터 조회: 성공 (55개 종목) [출처: yfinance]"
    assert log.summary_lines()[1] == "데이터 품질 판정: 부분 성공 (52/55; 3개 제외)"


def test_failure_recorded_and_reraised():
    repo = FakeRepo()
    log = RunLogger("r2", repo, clock=clock())
    with pytest.raises(DataQualityError):
        with log.step("data_quality"):
            raise DataQualityError("SPY 결측", code="DATA_REQUIRED_MISSING")
    rec = log.records()[0]
    assert rec.status == StepStatus.FAILED
    assert rec.error_code == "DATA_REQUIRED_MISSING"
    assert format_step_line(rec) == "데이터 품질 판정: 실패 (DATA_REQUIRED_MISSING: SPY 결측)"


def test_unexpected_error_code():
    log = RunLogger("r3", FakeRepo(), clock=clock())
    with pytest.raises(ZeroDivisionError):
        with log.step("metrics"):
            1 / 0  # noqa: B018
    assert log.records()[0].error_code == "UNEXPECTED_ERROR"


def test_store_failure_does_not_break_analysis(caplog):
    repo = FakeRepo()
    repo.fail_save_step = True
    log = RunLogger("r4", repo, clock=clock())
    with log.step("backtest") as h:
        h.set_summary("ok")
    assert log.records()[0].status == StepStatus.SUCCESS
    assert "실행 기록 저장 실패" in caplog.text
