# MyFinSight — 묶음 D (결과·통합)

LLM 없이 고정 Profile·고정 Spec → Universe 필터 → 가격 수집 → 전략 실행 → Backtest →
텍스트 Report(근거 포함)까지 이어지는 프로토타입에서 **묶음 D** 가 맡은 모듈의 구현입니다.
근거 문서: 「MyFinSight 프로토타입 모듈 명세 & 분배」(v1, 2026-10-02), UC 정리, 상위 요구사항 정리.

## 담당 모듈

| ID | 모듈 | 위치 | FR |
|---|---|---|---|
| M00-02 | 도메인 스키마 + 공통 오류 | `src/myfinsight/schemas/` | 전체 |
| M06-01 | 근거 생성기 | `src/myfinsight/report/evidence.py` | FR26, FR05 |
| M06-02 | Report 조립기 | `src/myfinsight/report/assembler.py` | FR14 |
| (부록 D) | 표시 규칙 | `src/myfinsight/report/display.py` | — |
| M04-03 | 일치성 검사기 | `src/myfinsight/validation/consistency.py` | FR10, FR25 |
| M08-01 | 실행 기록기 (Run Logger) | `src/myfinsight/runtime/runlog.py` | FR24 |
| M08-02 | 파이프라인 실행기 + CLI | `src/myfinsight/runtime/pipeline.py`, `cli.py` | FR24, FR25 |

다른 묶음(A 데이터, B 전략·검증, C 백테스트) 모듈은 `runtime/ports.py` 의 `PipelinePorts`
계약으로 연결합니다. 실제 연결은 `runtime/wiring.py` (`DefaultPorts`), 합의할 함수 이름·인자는
[docs/INTEGRATION.md](docs/INTEGRATION.md) 에 정리했습니다.

단계별 데이터 흐름·수식·검사 항목을 그림으로 정리한 설명서: [docs/dataflow.html](docs/dataflow.html)
(브라우저로 열기).

### ports 란

`PipelinePorts` 는 파이프라인이 다른 묶음 모듈을 부를 때 쓰는 연결 규격입니다. 메서드 이름과
입력·출력 타입만 정해 두고, 파이프라인은 이 규격의 메서드만 호출합니다. 규격을 만족하는 객체를
바꿔 끼우는 방식이라 실제 모듈(`wiring.DefaultPorts`) 대신 테스트용 가짜(`tests/conftest.py`
`FakePorts`)를 넣어 A·B·C 없이도 13단계 전체를 테스트할 수 있습니다. 다른 묶음 모듈이 완성되면
파이프라인은 그대로 두고 `wiring.py` 의 연결 줄만 맞추면 됩니다.

## 실행

```bash
pip install -e ".[dev]"
python -m myfinsight run --profile inputs/profile.json --spec inputs/spec.json \
    [--config config/config.toml] [--refresh-constituents]
python -m myfinsight steps <run_id>      # 분석 건별 단계 기록 조회 (R9)
```

종료 코드: `0` 성공 / `1` 분석 실패(사유 출력) / `2` 입력·설정 오류.
묶음 A·B·C 모듈이 합류하기 전에는 `CONFIG_MODULE_MISSING` 으로 어떤 모듈이 빠졌는지 알려 줍니다.

## 테스트

```bash
pytest          # 네트워크 없음 (Fake 어댑터, C-11)
ruff check src tests
```

`tests/conftest.py` 의 `FakePorts` 가 묶음 A·B·C를 대신해 파이프라인을 끝까지 실행합니다
(통합 테스트 = 부록 A 예시 Profile·Spec → Report 생성). 시나리오의 상한 재분배 값
`[0.30, 0.25, 0.20, 0.15, 0.10] → [0.15, 0.25, 0.25, 0.21, 0.14]` 는 손계산입니다.

## 실행 흐름 (M08-02)

```
설정 로드 → 저장소 열기 → run_id 발급(YYYYMMDD-HHMMSS-<6자리 해시>)
 1 load_profile → validate_spec
 2 constituents (고정 Universe면 SKIPPED) → universe → save_run_artifact
 3 fetch_prices → data_quality (제외 종목 있으면 PARTIAL)
 4 compute_weights → validate_weights
 5 backtest → metrics
 6 evidence → report → consistency → Report 저장(DB + outputs/report_<run_id>.md)
```

오류 정책: 필수 데이터 실패·Universe 0개·Spec/비중 검증 실패·Backtest 오류·일치성 실패는
중단(Report 미생성, 종료 코드 1), 입력·설정 오류는 종료 코드 2, 구성종목 갱신 실패(기존
스냅샷 있음)는 계속하고 PARTIAL + 한계 항목으로 남깁니다. Report 12번 섹션은 Report 생성
시점까지의 단계를 담으며, 이후 `consistency` 결과는 실행 기록(`steps` 명령)에서 확인합니다.

## 명세 대비 결정·변경 사항 (스키마 담당 공지)

M00-02 「스키마 변경 시 버전 메모」 규칙에 따라 명세와 다른 부분을 적어 둡니다.

1. `PerformanceMetrics.sharpe: float | None` — M05-02 「변동성 0이면 Sharpe 대신
   `METRIC_UNDEFINED` 표시(예외 아님)」를 표현하려고 `None` 을 허용. 표시는 `METRIC_UNDEFINED`.
2. `TickerSignal.metric_name` 표준값 상수 추가: `METRIC_VOLATILITY = "ann_volatility"`,
   `METRIC_MOMENTUM = "momentum"` (`schemas/results.py`). M03-01·M03-02는 이 이름으로 채워 주세요.
   M06-01이 이 이름으로 선정 근거를 찾습니다.
3. M06-01 입력에 `StrategySpec` 추가 — 근거 템플릿의 `{lookback}`, `{n}`, `{rule_name}`, 상한값이
   Spec에 있기 때문.
4. `EvidenceItem.values` 참조 키 규약 — `signal.<metric>`, `rank.<metric>`, `weight.pre_cap`,
   `weight.final`, `metrics.<경로>` 키는 M04-03 CONSIST_EVIDENCE가 원본과 대조합니다.
5. 표시값 경로(`display_values` 키) 규약 — `allocation.<TICKER>.weight` 처럼 ReportData 안의 값을
   가리키며, 경로별 표시 규칙은 `report/display.py` 한 곳에 둡니다 (M06-02·M04-03 공용).
6. Enum은 명세대로 `(str, Enum)` 을 유지 (ruff UP042 예외 처리).
7. 고정 Universe Spec이면 `constituents` 단계를 실행하지 않고 SKIPPED로 기록 (명세는 13단계 기록).
8. 근거 항목 추가 — 상한 초과분 재분배로 비중이 늘어난 종목에도 `cap` 문장, 누적수익률을
   Benchmark와 비교하는 `metric` 문장 1건.
9. 일치성 검사 범위 확장 — Spec 해시를 WeightSet과도 대조, 배분표 행 단위 대조, 본문의 투자 권유
   표현 검출(`CONSIST_TEXT`).
10. CLI 추가 — `steps <run_id>` 명령(R9 분석 건별 단계 확인), `--output-dir` 옵션.
11. `docs/INTEGRATION.md` 의 다른 묶음 함수 이름·인자는 제안안 (명세에 이름이 없음, 합의 필요).
