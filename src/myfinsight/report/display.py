"""부록 D 표시 규칙 (M06-01·M06-02·M04-03 공통).

- 비율(%): 소수 둘째 자리 (``15.23%``), 부호 있는 값은 ``+``/``-`` 표시
- 비중: 소수 첫째 자리 (``21.4%``)
- 원화: 원 단위 정수, 천 단위 쉼표 (``7,500,000원``) / 달러: 소수 둘째 자리 (``$5,432.10``)
- Sharpe: 소수 둘째 자리 / 날짜: ``YYYY-MM-DD``
- 반올림: 사사오입 (ROUND_HALF_UP)

표시값 경로(display path)는 ReportData 안의 값을 가리키는 점(.) 구분 문자열이다.
M06-02는 경로별로 :func:`format_path` 결과를 텍스트에 쓰고 ``display_values`` 에 기록하며,
M04-03은 같은 경로를 :func:`resolve_path` 로 다시 읽어 표시 문자열을 대조한다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from myfinsight.schemas.report import ReportData

UNDEFINED_TEXT = "METRIC_UNDEFINED"


def round_half_up(value: float, ndigits: int = 0) -> Decimal:
    """사사오입 반올림. 부동소수 표현 오차를 피하려고 ``repr`` 기준 Decimal로 변환한다."""
    quant = Decimal(1).scaleb(-ndigits)
    return Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP)


def krw_amount(amount_usd: float, fx_krw_per_usd: float) -> int:
    """달러 금액을 원 단위 정수로 환산한다 (사사오입)."""
    return int(round_half_up(amount_usd * fx_krw_per_usd, 0))


def _signed(text: str, value: Decimal, signed: bool) -> str:
    if signed and value > 0:
        return "+" + text
    return text


def fmt_pct(value: float | None, *, signed: bool = False) -> str:
    """비율(소수)을 퍼센트 두 자리로 표시한다. 예: 0.15234 → ``15.23%``."""
    if value is None:
        return UNDEFINED_TEXT
    d = round_half_up(value * 100, 2)
    if d == 0:
        d = abs(d)
    return _signed(f"{d:.2f}%", d, signed)


def fmt_weight(value: float) -> str:
    """비중을 퍼센트 한 자리로 표시한다. 예: 0.214 → ``21.4%``."""
    d = round_half_up(value * 100, 1)
    return f"{abs(d) if d == 0 else d:.1f}%"


def fmt_krw(value: float) -> str:
    """원화 금액. 예: 7500000 → ``7,500,000원``."""
    d = round_half_up(value, 0)
    return f"{int(d):,}원"


def fmt_usd(value: float) -> str:
    """달러 금액. 예: 5432.1 → ``$5,432.10``."""
    d = round_half_up(value, 2)
    sign = "-" if d < 0 else ""
    return f"{sign}${abs(d):,.2f}"


def fmt_sharpe(value: float | None) -> str:
    """Sharpe 소수 둘째 자리. 계산 불가(None)면 ``METRIC_UNDEFINED``."""
    if value is None:
        return UNDEFINED_TEXT
    d = round_half_up(value, 2)
    return f"{abs(d) if d == 0 else d:.2f}"


def fmt_date(value: date | datetime) -> str:
    """날짜 ``YYYY-MM-DD``."""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%Y-%m-%d")


def fmt_rate(value: float) -> str:
    """환율 등 일반 수치 소수 둘째 자리 (천 단위 쉼표)."""
    return f"{round_half_up(value, 2):,.2f}"


def fmt_bps(value: float) -> str:
    """거래비용 bp. 예: 10.0 → ``10.0bp``."""
    return f"{round_half_up(value, 1):.1f}bp"


# ---------------------------------------------------------------------------
# 표시값 경로 → 포맷터 규칙. 먼저 일치하는 규칙을 쓴다.
# ---------------------------------------------------------------------------
_PERF_SIGNED = r"(total_return|cagr|mdd)"
_PATH_RULES: list[tuple[re.Pattern[str], Callable[[Any], str]]] = [
    (re.compile(r"^allocation\.[^.]+\.weight$"), fmt_weight),
    (re.compile(r"^allocation\.[^.]+\.amount_usd$"), fmt_usd),
    (re.compile(r"^allocation\.[^.]+\.amount_krw$"), fmt_krw),
    (re.compile(rf"^metrics\.(strategy|benchmark)\.{_PERF_SIGNED}$"),
     lambda v: fmt_pct(v, signed=True)),
    (re.compile(r"^metrics\.(strategy|benchmark)\.ann_volatility$"), fmt_pct),
    (re.compile(r"^metrics\.(strategy|benchmark)\.sharpe$"), fmt_sharpe),
    (re.compile(r"^metrics\.(strategy|benchmark)\.mdd_(peak|trough)$"), fmt_date),
    (re.compile(r"^metrics\.excess_(total_return|cagr)$"), lambda v: fmt_pct(v, signed=True)),
    (re.compile(r"^conditions\.(start|end|fx_as_of)$"), fmt_date),
    (re.compile(r"^conditions\.initial_capital_usd$"), fmt_usd),
    (re.compile(r"^conditions\.fx_rate_krw_per_usd$"), fmt_rate),
    (re.compile(r"^conditions\.cost_bps$"), fmt_bps),
    (re.compile(r"^conditions\.risk_free_annual$"), fmt_pct),
    (re.compile(r"^profile\.investment_amount_krw$"), fmt_krw),
    (re.compile(r"^profile\.loss_tolerance_pct$"), lambda v: fmt_pct(v / 100)),
    (re.compile(r"^profile\.constraints\.max_weight_all$"), fmt_weight),
    (re.compile(r"^spec\.constraints\.max_weight_all$"), fmt_weight),
    (re.compile(r"^(profile|spec)\.constraints\.max_weight_per_ticker\.[^.]+$"), fmt_weight),
    (re.compile(r"^allocation_as_of$"), fmt_date),
    (re.compile(r"^total\.(amount_usd)$"), fmt_usd),
    (re.compile(r"^total\.(amount_krw)$"), fmt_krw),
    (re.compile(r"^total\.(weight)$"), fmt_weight),
]


def formatter_for(path: str) -> Callable[[Any], str]:
    """경로에 맞는 부록 D 포맷터를 돌려준다. 규칙이 없으면 ``KeyError``."""
    for pattern, fn in _PATH_RULES:
        if pattern.match(path):
            return fn
    raise KeyError(f"표시 규칙이 없는 경로: {path}")


def resolve_path(data: ReportData, path: str) -> Any:
    """표시값 경로가 가리키는 ReportData 원본 값을 읽는다.

    ``allocation.<TICKER>.<field>`` 는 해당 티커의 배분 행,
    ``total.<field>`` 는 배분 행 합계를 뜻한다.
    """
    parts = path.split(".")
    head = parts[0]
    if head == "allocation":
        if len(parts) != 3:
            raise KeyError(path)
        rows = [r for r in data.allocation if r.ticker == parts[1]]
        if not rows:
            raise KeyError(path)
        return getattr(rows[0], parts[2])
    if head == "total":
        if len(parts) != 2 or parts[1] not in {"weight", "amount_usd", "amount_krw"}:
            raise KeyError(path)
        return sum(getattr(r, parts[1]) for r in data.allocation)
    obj: Any = data
    for part in parts:
        if isinstance(obj, dict):
            if part not in obj:
                raise KeyError(path)
            obj = obj[part]
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            raise KeyError(path)
    return obj


def format_path(data: ReportData, path: str) -> str:
    """경로의 원본 값을 부록 D 규칙으로 표시한다."""
    return formatter_for(path)(resolve_path(data, path))
