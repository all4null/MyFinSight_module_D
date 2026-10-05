import pytest

from myfinsight.validation.consistency import check_consistency
from test_assembler import make_report


def check(sc, report, **over):
    kw = dict(spec=sc.spec, weights=sc.weights, backtest=sc.backtest, metrics=sc.metrics)
    kw.update(over)
    return check_consistency(report, **kw)


def codes(result):
    return {i.code for i in result.issues}


def test_normal_run_has_no_issues(scenario):
    result = check(scenario, make_report(scenario))
    assert result.ok, result.issues


def test_spec_mismatch(scenario):
    other = scenario.spec.model_copy(update={"period_years": 3})
    assert "CONSIST_SPEC" in codes(check(scenario, make_report(scenario), spec=other))
    bt = scenario.backtest.model_copy(update={"spec_hash": "0" * 64})
    assert codes(check(scenario, make_report(scenario), backtest=bt)) == {"CONSIST_SPEC"}


def _tamper_row(report, ticker, **update):
    data = report.data
    rows = [r.model_copy(update=update) if r.ticker == ticker else r for r in data.allocation]
    return report.model_copy(update={"data": data.model_copy(update={"allocation": rows})})


def test_weight_mismatch(scenario):
    bad = _tamper_row(make_report(scenario), "NVDA", weight=0.16)
    assert "CONSIST_WEIGHTS" in codes(check(scenario, bad))


def test_ticker_set_mismatch(scenario):
    report = make_report(scenario)
    rows = [r for r in report.data.allocation if r.ticker != "ORCL"]
    bad = report.model_copy(update={"data": report.data.model_copy(update={"allocation": rows})})
    assert "CONSIST_WEIGHTS" in codes(check(scenario, bad))


@pytest.mark.parametrize("field,delta", [("amount_usd", 1.0), ("amount_krw", 5)])
def test_amount_mismatch(scenario, field, delta):
    report = make_report(scenario)
    row = next(r for r in report.data.allocation if r.ticker == "AAPL")
    bad = _tamper_row(report, "AAPL", **{field: getattr(row, field) + delta})
    assert "CONSIST_AMOUNT" in codes(check(scenario, bad))


def test_amount_krw_within_one_won_ok(scenario):
    report = make_report(scenario)
    row = next(r for r in report.data.allocation if r.ticker == "AAPL")
    ok = _tamper_row(report, "AAPL", amount_krw=row.amount_krw + 1)
    assert "CONSIST_AMOUNT" not in codes(check(scenario, ok))


def test_metrics_mismatch(scenario):
    report = make_report(scenario)
    m = report.data.metrics
    bad_m = m.model_copy(update={"strategy": m.strategy.model_copy(update={"cagr": 0.2})})
    bad = report.model_copy(update={"data": report.data.model_copy(update={"metrics": bad_m})})
    assert "CONSIST_METRICS" in codes(check(scenario, bad))


def test_text_display_value_tampered(scenario):
    report = make_report(scenario)
    values = dict(report.display_values, **{"metrics.strategy.cagr": "+99.99%"})
    assert "CONSIST_TEXT" in codes(check(scenario, report.model_copy(
        update={"display_values": values})))


def test_text_markdown_tampered(scenario):
    report = make_report(scenario)
    text = report.text_markdown.replace("| NVDA | NVIDIA Corp. | 15.0% |",
                                        "| NVDA | NVIDIA Corp. | 25.0% |")
    assert "CONSIST_TEXT" in codes(check(scenario, report.model_copy(
        update={"text_markdown": text})))


def test_text_missing_required_value(scenario):
    report = make_report(scenario)
    values = {k: v for k, v in report.display_values.items() if k != "metrics.strategy.mdd"}
    assert "CONSIST_TEXT" in codes(check(scenario, report.model_copy(
        update={"display_values": values})))


def test_text_advice_detected(scenario):
    report = make_report(scenario)
    bad = report.model_copy(update={"text_markdown": report.text_markdown + "\nNVDA는 유망합니다."})
    assert "CONSIST_TEXT" in codes(check(scenario, bad))


def _tamper_evidence(report, idx, **update):
    ev = list(report.data.evidence)
    ev[idx] = ev[idx].model_copy(update=update)
    return report.model_copy(update={"data": report.data.model_copy(update={"evidence": ev})})


def test_evidence_value_mismatch(scenario):
    report = make_report(scenario)
    idx = next(i for i, e in enumerate(report.data.evidence)
               if e.subject == "MSFT" and e.kind == "selection")
    values = dict(report.data.evidence[idx].values, **{"signal.ann_volatility": 0.5})
    assert "CONSIST_EVIDENCE" in codes(check(scenario, _tamper_evidence(report, idx,
                                                                        values=values)))


def test_evidence_missing_source(scenario):
    bad = _tamper_evidence(make_report(scenario), 0, source=" ")
    assert "CONSIST_EVIDENCE" in codes(check(scenario, bad))


def test_evidence_missing_for_ticker(scenario):
    report = make_report(scenario)
    ev = [e for e in report.data.evidence if not (e.subject == "ORCL" and e.kind == "weight")]
    bad = report.model_copy(update={"data": report.data.model_copy(update={"evidence": ev})})
    assert "CONSIST_EVIDENCE" in codes(check(scenario, bad))


def test_evidence_metric_mismatch(scenario):
    report = make_report(scenario)
    idx = next(i for i, e in enumerate(report.data.evidence) if "metrics.strategy.mdd" in e.values)
    values = dict(report.data.evidence[idx].values, **{"metrics.strategy.mdd": -0.1})
    assert "CONSIST_EVIDENCE" in codes(check(scenario, _tamper_evidence(report, idx,
                                                                        values=values)))
