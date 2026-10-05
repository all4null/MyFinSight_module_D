from datetime import date

import pytest
from pydantic import ValidationError

from conftest import PROFILE_PATH, SPEC_PATH, load_json, make_scenario
from myfinsight.schemas import (
    BacktestResult,
    ConfigError,
    ConsistencyError,
    DataQualityReport,
    InputError,
    MetricsBundle,
    MyFinSightError,
    ProfileConstraints,
    StepRecord,
    StepStatus,
    StrategySpec,
    UserProfile,
    WeightSet,
)


def test_example_inputs_validate():
    profile = UserProfile.model_validate(load_json(PROFILE_PATH))
    spec = StrategySpec.model_validate(load_json(SPEC_PATH))
    assert profile.constraints.max_weight_per_ticker == {"NVDA": 0.15}
    assert spec.selection.rule.value == "low_volatility_top_n"


def test_extra_fields_rejected():
    data = load_json(PROFILE_PATH)
    data["risk_tpye"] = "오타"
    with pytest.raises(ValidationError):
        UserProfile.model_validate(data)
    spec = load_json(SPEC_PATH)
    spec["constraints"]["max_weigth_all"] = 0.3
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec)


def test_per_ticker_cap_range():
    with pytest.raises(ValidationError):
        ProfileConstraints(max_weight_per_ticker={"NVDA": 1.5})


@pytest.mark.parametrize(
    "attr", ["profile", "spec", "universe", "quality", "price_meta", "weights", "backtest",
             "metrics"],
)
def test_json_roundtrip(attr):
    model = getattr(make_scenario(), attr)
    again = type(model).model_validate_json(model.model_dump_json())
    assert again == model


def test_backtest_date_keys_roundtrip():
    bt = make_scenario().backtest
    again = BacktestResult.model_validate_json(bt.model_dump_json())
    assert all(isinstance(k, date) for k in again.equity_curve)


def test_spec_hash_stable_and_sensitive():
    spec = StrategySpec.model_validate(load_json(SPEC_PATH))
    same = StrategySpec.model_validate_json(spec.model_dump_json())
    assert spec.spec_hash() == same.spec_hash()
    assert len(spec.spec_hash()) == 64
    changed = spec.model_copy(update={"period_years": 3})
    assert changed.spec_hash() != spec.spec_hash()


def test_step_record_and_models_roundtrip():
    rec = StepRecord(run_id="r", step="backtest", status=StepStatus.FAILED,
                     started_at=make_scenario().price_meta.fetched_at, error_code="BACKTEST_X")
    assert StepRecord.model_validate_json(rec.model_dump_json()) == rec
    for cls in (WeightSet, MetricsBundle, DataQualityReport):
        assert cls.model_config.get("extra") == "forbid"


def test_errors_carry_code():
    err = InputError("bad", code="PROFILE_INVALID", details={"issues": [1]})
    assert isinstance(err, MyFinSightError)
    assert err.code == "PROFILE_INVALID" and err.details == {"issues": [1]}
    assert str(err) == "[PROFILE_INVALID] bad"
    assert ConfigError("x").code == "CONFIG_INVALID"
    assert ConsistencyError("x").code.startswith("CONSIST_")
    assert MyFinSightError("x").code == "UNKNOWN"
