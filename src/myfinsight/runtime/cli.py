"""CLI 진입점.

``python -m myfinsight run --profile inputs/profile.json --spec inputs/spec.json
[--config config/config.toml] [--refresh-constituents]``

``python -m myfinsight steps <run_id> [--config ...]`` — 분석 건별 단계 기록 조회 (R9)
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from myfinsight.report.display import fmt_pct, fmt_sharpe
from myfinsight.runtime.pipeline import (
    EXIT_ANALYSIS_FAILED,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    Pipeline,
    RunOutcome,
    RunRequest,
)
from myfinsight.runtime.ports import PipelinePorts
from myfinsight.runtime.runlog import STEP_LABELS, format_step_line
from myfinsight.schemas.errors import MyFinSightError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myfinsight", description="MyFinSight 프로토타입")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="고정 Profile·Spec으로 분석을 실행한다")
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--spec", type=Path, required=True)
    run.add_argument("--config", type=Path, default=Path("config/config.toml"))
    run.add_argument("--refresh-constituents", action="store_true")
    run.add_argument("--output-dir", type=Path, default=Path("outputs"))

    steps = sub.add_parser("steps", help="실행 건의 단계 기록을 조회한다")
    steps.add_argument("run_id")
    steps.add_argument("--config", type=Path, default=Path("config/config.toml"))
    return parser


def print_outcome(outcome: RunOutcome) -> None:
    """실행 결과를 콘솔에 출력한다."""
    if outcome.exit_code == EXIT_OK and outcome.report is not None:
        m = outcome.report.data.metrics.strategy
        print(f"분석 완료: run_id={outcome.run_id}")
        print(f"Report: {outcome.report_path}")
        print(
            f"누적수익률 {fmt_pct(m.total_return, signed=True)} / "
            f"CAGR {fmt_pct(m.cagr, signed=True)} / 변동성 {fmt_pct(m.ann_volatility)} / "
            f"Sharpe {fmt_sharpe(m.sharpe)} / MDD {fmt_pct(m.mdd, signed=True)}"
        )
        return
    kind = "입력·설정 오류" if outcome.exit_code == EXIT_INPUT_ERROR else "분석 실패"
    step = STEP_LABELS.get(outcome.failed_step or "", outcome.failed_step or "준비")
    print(f"{kind} (run_id={outcome.run_id or '-'}): [{step}] {outcome.error}", file=sys.stderr)
    for line in outcome.summary_lines:
        print(f"  - {line}", file=sys.stderr)


def main(argv: Sequence[str] | None = None, ports: PipelinePorts | None = None) -> int:
    """CLI 실행. 종료 코드 0 성공 / 1 분석 실패 / 2 입력·설정 오류."""
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if ports is None:
        from myfinsight.runtime.wiring import DefaultPorts

        ports = DefaultPorts()

    if args.command == "steps":
        try:
            repo = ports.open_repository(ports.load_config(args.config))
            records = repo.get_steps(args.run_id)
        except MyFinSightError as exc:
            print(f"조회 실패: {exc}", file=sys.stderr)
            return EXIT_INPUT_ERROR
        if not records:
            print(f"실행 기록 없음: {args.run_id}", file=sys.stderr)
            return EXIT_ANALYSIS_FAILED
        for rec in records:
            print(format_step_line(rec))
        return EXIT_OK

    outcome = Pipeline(ports).run(RunRequest(
        profile_path=args.profile, spec_path=args.spec, config_path=args.config,
        refresh_constituents=args.refresh_constituents, output_dir=args.output_dir,
    ))
    print_outcome(outcome)
    return outcome.exit_code
