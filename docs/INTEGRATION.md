# 묶음 간 연결 — 합의할 공개 API

M08-02 파이프라인은 `src/myfinsight/runtime/ports.py` 의 `PipelinePorts` 에만 의존합니다.
`runtime/wiring.py` 의 `DefaultPorts` 는 아래 이름으로 각 묶음 모듈을 import 해서 호출합니다.
이름·인자를 바꾸고 싶으면 이 표와 `wiring.py` 를 함께 고쳐 주세요 (묶음 D가 반영).

모든 입출력은 M00-02 스키마(`myfinsight.schemas`)이며, 실패는 `MyFinSightError` 하위 예외 + `code`.
`config` 는 M00-01 `AppConfig` 객체를 그대로 넘깁니다.

| 단계 | 묶음 | 모듈 | 호출 | 반환 / 실패 |
|---|---|---|---|---|
| 설정 | C | M00-01 | `myfinsight.config.load_config(path)` | `AppConfig` / `ConfigError` |
| 저장소 | A | M02-04 | `myfinsight.data.repository.SqliteRepository(db_url)` | `MarketDataRepository` 구현 |
| load_profile | B | M01-01 | `myfinsight.profile.load_profile(path, config, repo)` | `UserProfile` / `InputError(PROFILE_INVALID)` |
| validate_spec | B | M04-01 | `myfinsight.validation.spec_validator.validate_spec(spec, profile, config)` | `ValidationResult` |
| constituents | A | M02-05 | `myfinsight.data.constituents.ensure_constituents(repo, config, today, force)` | `(dict[IndexCode, list[IndexConstituent]], list[str] 경고)` |
| universe | B | M03-05 | `myfinsight.strategy.universe.build_universe(constituents, profile, spec, config)` | `UniverseResult` / `StrategyError(UNIVERSE_EMPTY)` |
| fetch_prices | A | M02-01·02·04 | `myfinsight.data.load_prices(repo, tickers, spec, config, today)` | `(PriceFrame, PriceMeta)` — tickers + Benchmark, 기간 = Backtest 기간 + 최대 lookback |
| data_quality | A | M02-03 | `myfinsight.data.quality.assess_quality(prices, spec, config)` | `(DataQualityReport, PriceFrame)` / `DataQualityError` |
| compute_weights | B | M03-04 | `myfinsight.strategy.executor.compute_weights(spec, universe, prices, as_of)` | `WeightSet` |
| validate_weights | B | M04-02 | `myfinsight.validation.weight_validator.validate_weights(weights, spec, universe)` | `ValidationResult` |
| backtest | C | M05-01 (+M05-03) | `myfinsight.backtest.simulator.run_backtest(spec, universe, prices, profile, config, repo)` | `BacktestResult` / `BacktestError` |
| metrics | C | M05-02 | `myfinsight.backtest.metrics.compute_metrics(backtest, config)` | `MetricsBundle` |

참고
- `ValidationResult(ok=False)` 를 받으면 M08-02가 첫 이슈의 `code` 로 `SpecValidationError` /
  `WeightValidationError` 를 던지고 중단합니다 (`details["issues"]` 에 전체 이슈).
- `compute_weights` 의 `as_of` 는 실행일이며, as_of 전 거래일까지 자르는 것은 M03-04 책임(C-06).
- `universe` 인자는 Universe 결과 중 M02-03 사용 가능 종목만 남긴 목록입니다.
- `WeightSet.signals[].metric_name` 은 `METRIC_VOLATILITY` / `METRIC_MOMENTUM` 을 써 주세요.
- Repository는 `save_step`, `get_steps`, `save_run_artifact`, `save_report` 를 M08이 사용합니다.
