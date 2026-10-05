from datetime import UTC, datetime

import pytest

from conftest import PROFILE_PATH, SPEC_PATH, FakePorts
from myfinsight.runtime.cli import main
from myfinsight.runtime.pipeline import Pipeline, RunRequest, load_spec_file, make_run_id
from myfinsight.runtime.runlog import STANDARD_STEPS
from myfinsight.schemas import (
    BacktestError,
    ConfigError,
    DataQualityError,
    InputError,
    StepStatus,
    StrategyError,
    UniverseSpec,
    ValidationIssue,
    ValidationResult,
)

NOW = datetime(2026, 10, 5, 1, 2, 3, tzinfo=UTC)


def run(ports, tmp_path, **kw):
    req = RunRequest(profile_path=PROFILE_PATH, spec_path=SPEC_PATH,
                     output_dir=tmp_path / "outputs", **kw)
    return Pipeline(ports, clock=lambda: NOW).run(req)


def test_full_run_success(fake_ports, tmp_path):
    out = run(fake_ports, tmp_path)
    assert out.exit_code == 0, out.error
    assert out.run_id.startswith("20261005-010203-")
    assert [r.step for r in out.steps] == list(STANDARD_STEPS)
    statuses = {r.step: r.status for r in out.steps}
    assert statuses["data_quality"] == StepStatus.PARTIAL  # C99 제외
    assert all(s in (StepStatus.SUCCESS, StepStatus.PARTIAL) for s in statuses.values())
    assert out.report_path.read_text(encoding="utf-8") == out.report.text_markdown
    assert fake_ports.repo.reports[out.run_id] is out.report
    assert out.run_id in fake_ports.repo.artifacts
    assert len(fake_ports.repo.get_steps(out.run_id)) == 13
    assert "## 12. 분석 과정 요약" in out.report.text_markdown
    assert "데이터 품질 판정: 부분 성공" in out.report.text_markdown


def test_run_is_reproducible(tmp_path):
    a = run(FakePorts(), tmp_path / "a")
    b = run(FakePorts(), tmp_path / "b")
    assert a.run_id == b.run_id
    assert a.report.text_markdown == b.report.text_markdown


def test_run_id_format():
    rid = make_run_id(NOW, b"x")
    assert rid[:16] == "20261005-010203-" and len(rid) == 22


@pytest.mark.parametrize(
    ("method", "exc", "step", "code"),
    [
        ("load_profile", InputError("bad", code="PROFILE_INVALID"), "load_profile", 2),
        ("build_universe", StrategyError("0개", code="UNIVERSE_EMPTY"), "universe", 1),
        ("assess_quality", DataQualityError("SPY", code="DATA_REQUIRED_MISSING"),
         "data_quality", 1),
        ("run_backtest", BacktestError("x", code="BACKTEST_FAILED"), "backtest", 1),
        ("compute_metrics", RuntimeError("boom"), "metrics", 1),
    ],
)
def test_failures_stop_pipeline(fake_ports, tmp_path, method, exc, step, code):
    fake_ports.fail[method] = exc
    out = run(fake_ports, tmp_path)
    assert out.exit_code == code
    assert out.failed_step == step
    assert out.steps[-1].step == step and out.steps[-1].status == StepStatus.FAILED
    assert out.report is None and not fake_ports.repo.reports
    assert not (tmp_path / "outputs").exists()


def test_spec_validation_failure(fake_ports, tmp_path):
    fake_ports.spec_result = ValidationResult(ok=False, issues=[
        ValidationIssue(code="SPEC_PROFILE_VIOLATION", field="constraints.max_weight_all",
                        message="Spec 상한 > Profile 상한"),
        ValidationIssue(code="SPEC_BENCHMARK", field="benchmark", message="허용 안 됨")])
    out = run(fake_ports, tmp_path)
    assert out.exit_code == 1
    assert out.failed_step == "validate_spec"
    assert out.error.code == "SPEC_PROFILE_VIOLATION"
    assert len(out.error.details["issues"]) == 2
    assert "build_universe" not in fake_ports.calls


def test_weight_validation_failure(fake_ports, tmp_path):
    fake_ports.weight_result = ValidationResult(ok=False, issues=[
        ValidationIssue(code="WEIGHT_CAP", message="NVDA 상한 초과")])
    out = run(fake_ports, tmp_path)
    assert (out.exit_code, out.failed_step, out.error.code) == (1, "validate_weights", "WEIGHT_CAP")
    assert "run_backtest" not in fake_ports.calls


def test_consistency_failure_blocks_report(fake_ports, tmp_path, monkeypatch):
    bad = ValidationResult(ok=False, issues=[ValidationIssue(code="CONSIST_WEIGHTS", message="x")])
    monkeypatch.setattr("myfinsight.runtime.pipeline.check_consistency", lambda *a, **k: bad)
    out = run(fake_ports, tmp_path)
    assert (out.exit_code, out.failed_step, out.error.code) == (1, "consistency", "CONSIST_WEIGHTS")
    assert not fake_ports.repo.reports
    assert not (tmp_path / "outputs").exists()


def test_constituent_refresh_warning_continues(fake_ports, tmp_path):
    fake_ports.constituent_warnings = ["구성종목 갱신 실패: 기존 스냅샷(2026-09-21) 사용"]
    out = run(fake_ports, tmp_path)
    assert out.exit_code == 0
    rec = next(r for r in out.steps if r.step == "constituents")
    assert rec.status == StepStatus.PARTIAL
    assert fake_ports.constituent_warnings[0] in out.report.data.limitations


def test_fixed_universe_skips_constituents(fake_ports, tmp_path):
    fixed = tmp_path / "spec_fixed.json"
    spec = load_spec_file(SPEC_PATH).model_copy(update={
        "universe": UniverseSpec(mode="fixed", tickers=["AAPL", "MSFT"])})
    fixed.write_text(spec.model_dump_json(), encoding="utf-8")
    req = RunRequest(profile_path=PROFILE_PATH, spec_path=fixed, output_dir=tmp_path / "o")
    out = Pipeline(fake_ports, clock=lambda: NOW).run(req)
    rec = next(r for r in out.steps if r.step == "constituents")
    assert rec.status == StepStatus.SKIPPED
    assert "ensure_constituents" not in fake_ports.calls


def test_config_error_exit_2(fake_ports, tmp_path):
    fake_ports.fail["load_config"] = ConfigError("없음", code="CONFIG_NOT_FOUND")
    out = run(fake_ports, tmp_path)
    assert out.exit_code == 2 and out.run_id is None


def test_bad_spec_file_exit_2(fake_ports, tmp_path):
    bad = tmp_path / "spec.json"
    bad.write_text('{"spec_id": "x"}', encoding="utf-8")
    req = RunRequest(profile_path=PROFILE_PATH, spec_path=bad, output_dir=tmp_path / "o")
    out = Pipeline(fake_ports, clock=lambda: NOW).run(req)
    assert (out.exit_code, out.failed_step, out.error.code) == (2, "validate_spec",
                                                                 "INPUT_SPEC_INVALID")


def test_cli_run_and_steps(fake_ports, tmp_path, capsys):
    code = main(["run", "--profile", str(PROFILE_PATH), "--spec", str(SPEC_PATH),
                 "--output-dir", str(tmp_path / "out")], ports=fake_ports)
    assert code == 0
    out = capsys.readouterr().out
    assert "분석 완료" in out and "MDD -22.45%" in out
    run_id = out.split("run_id=")[1].split()[0]
    assert main(["steps", run_id], ports=fake_ports) == 0
    assert "일치성 검사: 성공" in capsys.readouterr().out


def test_cli_failure_output(fake_ports, tmp_path, capsys):
    fake_ports.fail["run_backtest"] = BacktestError("가격 없음", code="BACKTEST_NO_PRICE")
    code = main(["run", "--profile", str(PROFILE_PATH), "--spec", str(SPEC_PATH),
                 "--output-dir", str(tmp_path / "out")], ports=fake_ports)
    err = capsys.readouterr().err
    assert code == 1
    assert "분석 실패" in err and "[Backtest]" in err and "BACKTEST_NO_PRICE" in err


def test_default_ports_report_missing_module(tmp_path):
    from myfinsight.runtime.wiring import DefaultPorts

    out = Pipeline(DefaultPorts(), clock=lambda: NOW).run(RunRequest(
        profile_path=PROFILE_PATH, spec_path=SPEC_PATH, output_dir=tmp_path))
    assert out.exit_code == 2 and out.error.code == "CONFIG_MODULE_MISSING"
