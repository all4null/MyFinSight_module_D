"""M04-03 일치성 검사기 (FR10 표시=실행, FR25 Report 수치 불일치 차단).

검사만 하고 값을 고치지 않는다. 모든 항목을 검사해 이슈를 모아 반환하며,
실패하면 M08-02가 Report를 저장·출력하지 않고 ``ConsistencyError`` 로 처리한다.
"""

from __future__ import annotations

from typing import Any

from myfinsight.report.display import format_path, krw_amount
from myfinsight.report.evidence import contains_advice
from myfinsight.schemas.report import Report
from myfinsight.schemas.results import (
    BacktestResult,
    MetricsBundle,
    PerformanceMetrics,
    ValidationIssue,
    ValidationResult,
    WeightSet,
)
from myfinsight.schemas.spec import StrategySpec

WEIGHT_TOL = 1e-6
AMOUNT_USD_TOL = 1e-6
AMOUNT_KRW_TOL = 1
METRIC_TOL = 1e-9
EVIDENCE_TOL = 1e-9

_REQUIRED_METRIC_FIELDS = ("total_return", "cagr", "ann_volatility", "sharpe", "mdd")


def required_display_paths(report: Report) -> list[str]:
    """텍스트에 반드시 표시되어야 하는 주요 수치(비중·금액·지표)의 경로."""
    paths: list[str] = []
    for row in report.data.allocation:
        base = f"allocation.{row.ticker}"
        paths += [f"{base}.weight", f"{base}.amount_usd", f"{base}.amount_krw"]
    for side in ("strategy", "benchmark"):
        paths += [f"metrics.{side}.{f}" for f in _REQUIRED_METRIC_FIELDS]
    paths += ["metrics.excess_total_return", "metrics.excess_cagr"]
    return paths


def _check_spec(
    report: Report, spec: StrategySpec, weights: WeightSet, backtest: BacktestResult
) -> list[ValidationIssue]:
    expected = spec.spec_hash()
    found = {
        "report.spec_hash": report.data.spec_hash,
        "report.spec": report.data.spec.spec_hash(),
        "weights.spec_hash": weights.spec_hash,
        "backtest.spec_hash": backtest.spec_hash,
    }
    return [
        ValidationIssue(code="CONSIST_SPEC", field=name,
                        message=f"Spec 해시 불일치: {value[:12]} ≠ 실행 Spec {expected[:12]}")
        for name, value in found.items() if value != expected
    ]


def _check_weights(report: Report, weights: WeightSet) -> list[ValidationIssue]:
    issues = []
    shown = {r.ticker: r.weight for r in report.data.allocation}
    expected = {t: w for t, w in weights.weights.items() if w > 0}
    if set(shown) != set(expected):
        issues.append(ValidationIssue(
            code="CONSIST_WEIGHTS", field="allocation",
            message=f"종목 집합 불일치: Report {sorted(shown)} ≠ 실행 {sorted(expected)}",
        ))
    for ticker in sorted(set(shown) & set(expected)):
        if abs(shown[ticker] - expected[ticker]) > WEIGHT_TOL:
            issues.append(ValidationIssue(
                code="CONSIST_WEIGHTS", field=f"allocation.{ticker}.weight",
                message=f"{ticker} 비중 불일치: {shown[ticker]} ≠ {expected[ticker]}",
            ))
    if report.data.allocation_as_of != weights.as_of:
        issues.append(ValidationIssue(
            code="CONSIST_WEIGHTS", field="allocation_as_of",
            message=f"기준일 불일치: {report.data.allocation_as_of} ≠ {weights.as_of}",
        ))
    return issues


def _check_amounts(report: Report, backtest: BacktestResult) -> list[ValidationIssue]:
    issues = []
    cond = backtest.conditions
    if report.data.conditions != cond:
        issues.append(ValidationIssue(
            code="CONSIST_AMOUNT", field="conditions",
            message="Report 계산 조건이 Backtest 계산 조건과 다릅니다",
        ))
    for row in report.data.allocation:
        usd = row.weight * cond.initial_capital_usd
        if abs(row.amount_usd - usd) > AMOUNT_USD_TOL:
            issues.append(ValidationIssue(
                code="CONSIST_AMOUNT", field=f"allocation.{row.ticker}.amount_usd",
                message=f"{row.ticker} 달러 금액 불일치: {row.amount_usd} ≠ {usd}",
            ))
        krw = krw_amount(usd, cond.fx_rate_krw_per_usd)
        if abs(row.amount_krw - krw) > AMOUNT_KRW_TOL:
            issues.append(ValidationIssue(
                code="CONSIST_AMOUNT", field=f"allocation.{row.ticker}.amount_krw",
                message=f"{row.ticker} 원화 금액 불일치: {row.amount_krw} ≠ {krw}",
            ))
    return issues


def _diff_perf(prefix: str, got: PerformanceMetrics, exp: PerformanceMetrics) -> list[str]:
    bad = []
    for name in PerformanceMetrics.model_fields:
        a, b = getattr(got, name), getattr(exp, name)
        if isinstance(a, float) and isinstance(b, float):
            if abs(a - b) > METRIC_TOL:
                bad.append(f"{prefix}.{name}")
        elif a != b:
            bad.append(f"{prefix}.{name}")
    return bad


def _check_metrics(report: Report, metrics: MetricsBundle) -> list[ValidationIssue]:
    got = report.data.metrics
    bad = _diff_perf("metrics.strategy", got.strategy, metrics.strategy)
    bad += _diff_perf("metrics.benchmark", got.benchmark, metrics.benchmark)
    for name in ("excess_total_return", "excess_cagr"):
        if abs(getattr(got, name) - getattr(metrics, name)) > METRIC_TOL:
            bad.append(f"metrics.{name}")
    return [
        ValidationIssue(code="CONSIST_METRICS", field=path, message=f"지표 불일치: {path}")
        for path in bad
    ]


def _check_text(report: Report) -> list[ValidationIssue]:
    issues = []
    text = report.text_markdown
    values = report.display_values
    for path in required_display_paths(report):
        if path not in values:
            issues.append(ValidationIssue(code="CONSIST_TEXT", field=path,
                                          message=f"주요 수치가 표시값 목록에 없음: {path}"))
    for path, shown in sorted(values.items()):
        try:
            expected = format_path(report.data, path)
        except KeyError:
            issues.append(ValidationIssue(code="CONSIST_TEXT", field=path,
                                          message=f"ReportData에 없는 표시 경로: {path}"))
            continue
        if shown != expected:
            issues.append(ValidationIssue(
                code="CONSIST_TEXT", field=path,
                message=f"표시 문자열 불일치: '{shown}' ≠ 표시 규칙 '{expected}'",
            ))
        elif shown not in text:
            issues.append(ValidationIssue(code="CONSIST_TEXT", field=path,
                                          message=f"텍스트에 표시값 '{shown}' 없음"))
    # 배분표 행 단위 대조: 같은 행에 그 종목의 비중·금액이 있어야 한다
    lines = text.splitlines()
    for row in report.data.allocation:
        row_lines = [ln for ln in lines if ln.startswith(f"| {row.ticker} |")]
        base = f"allocation.{row.ticker}"
        expected_cells = [values.get(f"{base}.{f}") for f in ("weight", "amount_usd", "amount_krw")]
        if not row_lines or not all(c and c in row_lines[0] for c in expected_cells):
            issues.append(ValidationIssue(code="CONSIST_TEXT", field=base,
                                          message=f"배분표에 {row.ticker} 행 값이 맞지 않음"))
    if contains_advice(text):
        issues.append(ValidationIssue(code="CONSIST_TEXT", field="text_markdown",
                                      message="투자 권유 표현이 포함됨"))
    return issues


def _resolve_metric(metrics: MetricsBundle, path: str) -> Any:
    obj: Any = metrics
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _evidence_reference(
    key: str, subject: str, weights: WeightSet, metrics: MetricsBundle
) -> tuple[bool, Any]:
    """참조 키가 가리키는 원본 값. (참조 키 여부, 원본 값) — 원본이 없으면 값은 None."""
    if key.startswith("signal.") or key.startswith("rank."):
        kind, metric = key.split(".", 1)
        sig = next((s for s in weights.signals
                    if s.ticker == subject and s.metric_name == metric
                    and (kind == "signal" or s.rank is not None)), None)
        if sig is None:
            return True, None
        return True, sig.value if kind == "signal" else sig.rank
    if key == "weight.pre_cap":
        return True, weights.pre_cap_weights.get(subject, weights.weights.get(subject))
    if key == "weight.final":
        return True, weights.weights.get(subject)
    if key.startswith("metrics."):
        try:
            return True, _resolve_metric(metrics, key.removeprefix("metrics."))
        except AttributeError:
            return True, None
    return False, None


def _check_evidence(
    report: Report, spec: StrategySpec, weights: WeightSet, metrics: MetricsBundle
) -> list[ValidationIssue]:
    issues = []
    evidence = report.data.evidence
    for i, item in enumerate(evidence):
        field = f"evidence[{i}]"
        if not item.source.strip():
            issues.append(ValidationIssue(code="CONSIST_EVIDENCE", field=field,
                                          message=f"출처 없음: {item.statement}"))
        for key, value in item.values.items():
            is_ref, original = _evidence_reference(key, item.subject, weights, metrics)
            if not is_ref:
                continue
            ok = (
                original is not None and isinstance(value, int | float)
                and abs(float(value) - float(original)) <= EVIDENCE_TOL
            )
            if not ok:
                issues.append(ValidationIssue(
                    code="CONSIST_EVIDENCE", field=f"{field}.values.{key}",
                    message=f"{item.subject} 근거 수치 불일치: {key}={value} ≠ 원본 {original}",
                ))
    for row in report.data.allocation:
        kinds = {e.kind for e in evidence if e.subject == row.ticker}
        for needed in ("selection", "weight"):
            if needed not in kinds:
                issues.append(ValidationIssue(
                    code="CONSIST_EVIDENCE", field=f"evidence.{row.ticker}",
                    message=f"{row.ticker}에 {needed} 근거 없음",
                ))
        if spec.selection.rule.value != "fixed_list":
            has_signal = any(
                e.subject == row.ticker and e.kind == "selection"
                and any(k.startswith("signal.") for k in e.values)
                for e in evidence
            )
            if not has_signal:
                issues.append(ValidationIssue(
                    code="CONSIST_EVIDENCE", field=f"evidence.{row.ticker}",
                    message=f"{row.ticker} 선정 근거에 지표값이 없음",
                ))
    return issues


def check_consistency(
    report: Report,
    *,
    spec: StrategySpec,
    weights: WeightSet,
    backtest: BacktestResult,
    metrics: MetricsBundle,
) -> ValidationResult:
    """Report가 실행에 쓰인 Spec·기준일 비중·Backtest·지표와 일치하는지 검사한다."""
    issues = (
        _check_spec(report, spec, weights, backtest)
        + _check_weights(report, weights)
        + _check_amounts(report, backtest)
        + _check_metrics(report, metrics)
        + _check_text(report)
        + _check_evidence(report, spec, weights, metrics)
    )
    return ValidationResult(ok=not issues, issues=issues)
