"""M08-02 파이프라인 실행기 (FR24, FR25).

호출 순서와 오류 처리 정책만 가진다 (비즈니스 로직 금지). 각 모듈 호출은
``RunLogger.step()`` 으로 감싸며, 단계 함수는 :class:`PipelinePorts` 공개 API만 쓴다.

오류 처리 정책
- 일부 종목 데이터 제외(필수 아님) → 계속, 단계 PARTIAL, 한계에 기록
- 필수 데이터 실패·Universe 0개·Spec/비중 검증 실패·Backtest 오류·일치성 실패 → 중단, Report 미생성
- 구성종목 갱신 실패(기존 스냅샷 있음) → 계속, 경고·한계 기록

종료 코드: 0 성공 / 1 분석 실패 / 2 입력·설정 오류
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from myfinsight.report.assembler import assemble_report
from myfinsight.report.evidence import build_evidence
from myfinsight.runtime.ports import AppConfig, Constituents, PipelinePorts, RunRepository
from myfinsight.runtime.runlog import RunLogger
from myfinsight.schemas.enums import StepStatus
from myfinsight.schemas.errors import (
    ConfigError,
    ConsistencyError,
    InputError,
    MyFinSightError,
    RepositoryError,
    SpecValidationError,
    WeightValidationError,
)
from myfinsight.schemas.report import Report
from myfinsight.schemas.results import ValidationResult
from myfinsight.schemas.runlog import StepRecord
from myfinsight.schemas.spec import StrategySpec
from myfinsight.validation.consistency import check_consistency

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ANALYSIS_FAILED = 1
EXIT_INPUT_ERROR = 2


@dataclass(frozen=True)
class RunRequest:
    """CLI 입력."""

    profile_path: Path
    spec_path: Path
    config_path: Path = Path("config/config.toml")
    refresh_constituents: bool = False
    output_dir: Path = Path("outputs")


@dataclass
class RunOutcome:
    """실행 결과 (CLI가 출력)."""

    exit_code: int
    run_id: str | None = None
    report: Report | None = None
    report_path: Path | None = None
    failed_step: str | None = None
    error: MyFinSightError | None = None
    steps: list[StepRecord] = field(default_factory=list)
    summary_lines: list[str] = field(default_factory=list)


def make_run_id(now: datetime, *parts: bytes) -> str:
    """``YYYYMMDD-HHMMSS-<6자리 해시>`` (해시 = 시각 + 입력 내용의 SHA-256 앞 6자리)."""
    h = hashlib.sha256(now.isoformat().encode())
    for p in parts:
        h.update(p)
    return f"{now:%Y%m%d-%H%M%S}-{h.hexdigest()[:6]}"


def load_spec_file(path: Path) -> StrategySpec:
    """Spec JSON 파일을 읽어 스키마 검증한다. 실패 시 InputError."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Spec 파일을 읽을 수 없습니다: {path}", code="INPUT_SPEC_NOT_FOUND",
                         details={"path": str(path)}) from exc
    try:
        return StrategySpec.model_validate_json(raw)
    except ValidationError as exc:
        raise InputError(f"Spec 스키마 검증 실패: {path}", code="INPUT_SPEC_INVALID",
                         details={"errors": exc.errors(include_url=False)}) from exc


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return str(path).encode()


def _raise_if_invalid(
    result: ValidationResult, error_cls: type[MyFinSightError], what: str
) -> None:
    if result.ok:
        return
    first = result.issues[0]
    messages = "; ".join(f"{i.code}({i.field}): {i.message}" if i.field else
                         f"{i.code}: {i.message}" for i in result.issues)
    raise error_cls(
        f"{what} 실패 {len(result.issues)}건 — {messages}",
        code=first.code,
        details={"issues": [i.model_dump() for i in result.issues]},
    )


def _exit_code_for(exc: MyFinSightError) -> int:
    return EXIT_INPUT_ERROR if isinstance(exc, ConfigError | InputError) else EXIT_ANALYSIS_FAILED


class Pipeline:
    """분석 1건을 처음부터 끝까지 실행한다."""

    def __init__(
        self,
        ports: PipelinePorts,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ports = ports
        self.clock = clock

    def run(self, req: RunRequest) -> RunOutcome:
        """실행 흐름 0-2 순서대로 모듈을 호출한다. 예외를 삼키지 않고 종료 코드로 바꾼다."""
        try:
            config = self.ports.load_config(req.config_path)
            repo = self.ports.open_repository(config)
        except MyFinSightError as exc:
            logger.error("설정·저장소 준비 실패: %s", exc)
            return RunOutcome(exit_code=_exit_code_for(exc), error=exc)

        started = self.clock()
        run_id = make_run_id(started, _read_bytes(req.profile_path), _read_bytes(req.spec_path))
        run_log = RunLogger(run_id, repo, clock=self.clock)
        try:
            report, report_path = self._execute(req, config, repo, run_log, started)
        except Exception as exc:  # noqa: BLE001 - 모든 실패를 종료 코드·실패 단계로 보고한다
            if isinstance(exc, MyFinSightError):
                error, code = exc, _exit_code_for(exc)
            else:
                logger.exception("예상하지 못한 오류")
                error = MyFinSightError(repr(exc), code="UNEXPECTED_ERROR")
                code = EXIT_ANALYSIS_FAILED
            records = run_log.records()
            failed = next((r.step for r in records if r.status == StepStatus.FAILED), None)
            logger.error("분석 실패 [%s] %s", failed or "-", error)
            return RunOutcome(
                exit_code=code, run_id=run_id, failed_step=failed, error=error,
                steps=records, summary_lines=run_log.summary_lines(),
            )
        return RunOutcome(
            exit_code=EXIT_OK, run_id=run_id, report=report, report_path=report_path,
            steps=run_log.records(), summary_lines=run_log.summary_lines(),
        )

    def _execute(
        self,
        req: RunRequest,
        config: AppConfig,
        repo: RunRepository,
        run_log: RunLogger,
        started: datetime,
    ) -> tuple[Report, Path]:
        step = run_log.step
        run_id = run_log.run_id
        p = self.ports
        today = started.date()

        # 1. Profile 로드·검증 → Spec 파일 로드 → Spec 정적 검증
        with step("load_profile") as h:
            profile = p.load_profile(req.profile_path, config, repo)
            h.set_summary(f"{profile.profile_id} ({profile.risk_type.value})")
            h.add_source(str(req.profile_path))
        with step("validate_spec") as h:
            spec = p.load_spec(req.spec_path)
            h.add_source(str(req.spec_path))
            _raise_if_invalid(p.validate_spec(spec, profile, config), SpecValidationError,
                              "Spec 정적 검증")
            h.set_summary(f"{spec.spec_id} v{spec.version} 통과")

        # 2. 구성종목 확인 → Universe 필터링
        warnings: list[str] = []
        constituents: Constituents = {}
        if spec.universe.mode == "fixed" and not req.refresh_constituents:
            run_log.skip("constituents", "고정 Universe Spec")
        else:
            with step("constituents") as h:
                constituents, warnings = p.ensure_constituents(
                    repo, config, today, req.refresh_constituents
                )
                total = sum(len(v) for v in constituents.values())
                h.set_summary(", ".join(f"{k.value} {len(v)}" for k, v in
                                        sorted(constituents.items(), key=lambda kv: kv[0].value))
                              or f"{total}개")
                for rows in constituents.values():
                    for src in sorted({r.source for r in rows}):
                        h.add_source(src)
                if warnings:
                    h.mark_partial("; ".join(warnings))
        with step("universe") as h:
            universe = p.build_universe(constituents, profile, spec, config)
            h.set_summary(f"후보 {len(universe.tickers)}개")
            h.add_source(universe.source)
        repo.save_run_artifact(run_id, profile, spec, universe, config)  # 재현용

        # 3. 가격 수집(캐시 우선) → 정규화 → 저장 → 품질 판정
        with step("fetch_prices") as h:
            prices, price_meta = p.fetch_prices(repo, list(universe.tickers), spec, config, today)
            h.set_summary(f"{len(price_meta.tickers)}개 종목, 기준일 {price_meta.as_of}")
            h.add_source(price_meta.source)
        with step("data_quality") as h:
            quality, clean_prices = p.assess_quality(prices, spec, config)
            total = len(quality.items)
            h.set_summary(f"{len(quality.usable_tickers)}/{total}")
            h.add_source(price_meta.source)
            if quality.excluded:
                h.mark_partial(f"{len(quality.excluded)}개 제외")
        usable = set(quality.usable_tickers)
        candidates = [t for t in universe.tickers if t in usable]

        # 4. 기준일 비중 산출 → 동적 검증
        with step("compute_weights") as h:
            weights = p.compute_weights(spec, candidates, clean_prices, today)
            h.set_summary(f"{len(weights.weights)}개 종목 (기준일 {weights.as_of})")
        with step("validate_weights") as h:
            _raise_if_invalid(p.validate_weights(weights, spec, candidates),
                              WeightValidationError, "비중 동적 검증")
            h.set_summary("통과")

        # 5. Backtest → 지표
        with step("backtest") as h:
            backtest = p.run_backtest(spec, candidates, clean_prices, profile, config, repo)
            h.set_summary(f"{backtest.conditions.start} ~ {backtest.conditions.end}, "
                          f"리밸런싱 {len(backtest.rebalances)}회")
            h.add_source(price_meta.source)
        with step("metrics") as h:
            metrics = p.compute_metrics(backtest, config)
            h.set_summary("지표 산출 완료")

        # 6. 근거 생성 → Report 조립 → 일치성 검사 → 저장·출력
        with step("evidence") as h:
            evidence = build_evidence(
                universe=universe, weights=weights, quality=quality, metrics=metrics,
                profile=profile, price_meta=price_meta, spec=spec,
            )
            h.set_summary(f"근거 {len(evidence)}건")
        with step("report") as h:
            names = {r.ticker: r.name for rows in constituents.values() for r in rows}
            done = [r for r in run_log.records() if r.status != StepStatus.STARTED]
            report = assemble_report(
                run_id=run_id, created_at=started, profile=profile, spec=spec, weights=weights,
                backtest=backtest, metrics=metrics, evidence=evidence, universe=universe,
                quality=quality, steps=done, names=names, extra_limitations=warnings,
            )
            h.set_summary(f"표시값 {len(report.display_values)}개")
        with step("consistency") as h:
            _raise_if_invalid(
                check_consistency(report, spec=spec, weights=weights, backtest=backtest,
                                  metrics=metrics),
                ConsistencyError, "Report 일치성 검사",
            )
            h.set_summary("통과")

        return report, self._save_report(repo, report, req.output_dir)

    @staticmethod
    def _save_report(repo: RunRepository, report: Report, output_dir: Path) -> Path:
        repo.save_report(report)
        path = output_dir / f"report_{report.data.run_id}.md"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(report.text_markdown, encoding="utf-8")
        except OSError as exc:
            raise RepositoryError(f"Report 파일 저장 실패: {path}",
                                  code="REPO_WRITE_FAILED") from exc
        return path

