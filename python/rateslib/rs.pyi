from collections.abc import Sequence
from datetime import datetime
from typing import Any

from typing_extensions import Self

from rateslib.calendars import CalTypes
from rateslib.curves.rs import CurveInterpolator
from rateslib.dual import DualTypes, Number
from rateslib.dual.variable import Arr1dF64, Arr2dF64

class ADOrder:
    Zero: ADOrder
    One: ADOrder
    Two: ADOrder

class Convention:
    Act365F: Convention
    Act365FPlus: Convention
    Act360: Convention
    Thirty360: Convention
    ThirtyE360: Convention
    Thirty360ISDA: Convention
    ActActISDA: Convention
    ActActICMA: Convention
    One: Convention
    OnePlus: Convention
    Bus252: Convention

class Modifier:
    P: Modifier
    F: Modifier
    ModP: Modifier
    ModF: Modifier
    Act: Modifier

class RollDay:
    @classmethod
    def EoM(cls) -> RollDay: ...
    @classmethod
    def SoM(cls) -> RollDay: ...
    @classmethod
    def IMM(cls) -> RollDay: ...
    @classmethod
    def Int(cls, val: int) -> RollDay: ...
    @classmethod
    def Unspecified(cls) -> RollDay: ...

def get_named_calendar(name: str) -> Cal: ...

class _DateRoll:
    def add_bus_days(self, date: datetime, days: int, settlement: bool) -> datetime: ...
    def add_days(
        self, date: datetime, days: int, modifier: Modifier, settlement: bool
    ) -> datetime: ...
    def add_months(
        self, date: datetime, months: int, modifier: Modifier, roll: RollDay, settlement: bool
    ) -> datetime: ...
    def bus_date_range(self, start: datetime, end: datetime) -> list[datetime]: ...
    def cal_date_range(self, start: datetime, end: datetime) -> list[datetime]: ...
    def is_bus_day(self, date: datetime) -> bool: ...
    def is_non_bus_day(self, date: datetime) -> bool: ...
    def is_settlement(self, date: datetime) -> bool: ...
    def lag(self, date: datetime, days: int, settlement: bool) -> datetime: ...
    def roll(self, date: datetime, modifier: Modifier, settlement: bool) -> datetime: ...
    def to_json(self) -> str: ...

class Cal(_DateRoll):
    def __init__(self, rules: list[datetime], weekmask: list[int]) -> None: ...

class UnionCal(_DateRoll):
    def __init__(
        self,
        calendars: list[Cal | NamedCal | UnionCal],
        settlement_calendars: list[Cal | NamedCal | UnionCal] | None,
    ) -> None: ...

class NamedCal(_DateRoll):
    def __init__(self, name: str) -> None: ...

class Ccy:
    def __init__(self, name: str) -> None: ...
    name: str = ...

class FXRate:
    def __init__(
        self, lhs: str, rhs: str, rate: DualTypes, settlement: datetime | None
    ) -> None: ...
    rate: DualTypes = ...
    ad: int = ...
    settlement: datetime = ...
    pair: str = ...
    def __repr__(self) -> str: ...
    def __eq__(self, other: FXRate) -> bool: ...  # type: ignore[override]

class FXRates:
    def __init__(self, fx_rates: list[FXRate], base: Ccy | None) -> None: ...
    def __copy__(self) -> FXRates: ...
    fx_rates: list[FXRate] = ...
    currencies: list[Ccy] = ...
    ad: int = ...
    base: Ccy = ...
    fx_vector: list[DualTypes] = ...
    fx_array: list[list[DualTypes]] = ...
    def get_ccy_index(self, currency: Ccy) -> int | None: ...
    def rate(self, lhs: Ccy, rhs: Ccy) -> DualTypes | None: ...
    def update(self, fx_rates: list[FXRate]) -> None: ...
    def set_ad_order(self, ad: ADOrder) -> None: ...
    def to_json(self) -> str: ...

class _DualOps:
    def __eq__(self, other: Number) -> bool: ...  # type: ignore[override]
    def __lt__(self, other: Number) -> bool: ...
    def __le__(self, other: Number) -> bool: ...
    def __gt__(self, other: Number) -> bool: ...
    def __ge__(self, other: Number) -> bool: ...
    def __neg__(self) -> Self: ...
    def __add__(self, other: Number) -> Self: ...
    def __radd__(self, other: Number) -> Self: ...
    def __sub__(self, other: Number) -> Self: ...
    def __rsub__(self, other: Number) -> Self: ...
    def __mul__(self, other: Number) -> Self: ...
    def __rmul__(self, other: Number) -> Self: ...
    def __truediv__(self, other: Number) -> Self: ...
    def __rtruediv__(self, other: Number) -> Self: ...
    def __pow__(self, power: Number, modulo: int | None = None) -> Self: ...
    def __exp__(self) -> Self: ...
    def __abs__(self) -> float: ...
    def __log__(self) -> Self: ...
    def __norm_cdf__(self) -> Self: ...
    def __norm_inv_cdf__(self) -> Self: ...
    def __float__(self) -> float: ...
    def to_json(self) -> str: ...
    def ptr_eq(self, other: Self) -> bool: ...
    def __repr__(self) -> str: ...
    def grad1(self, vars: list[str]) -> Arr1dF64: ...
    def grad2(self, vars: list[str]) -> Arr2dF64: ...

class Dual(_DualOps):
    def __init__(self, real: float, vars: Sequence[str], dual: Sequence[float] | Arr1dF64): ...
    real: float = ...
    vars: list[str] = ...
    dual: Arr1dF64 = ...
    @classmethod
    def vars_from(
        cls, other: Dual, real: float, vars: Sequence[str], dual: Sequence[float] | Arr1dF64
    ) -> Dual: ...
    def to_dual2(self) -> Dual2: ...

class Dual2(_DualOps):
    def __init__(
        self,
        real: float,
        vars: Sequence[str],
        dual: Sequence[float] | Arr1dF64,
        dual2: Sequence[float],
    ): ...
    real: float = ...
    vars: list[str] = ...
    dual: Arr1dF64 = ...
    dual2: Arr2dF64 = ...
    @classmethod
    def vars_from(
        cls,
        other: Dual2,
        real: float,
        vars: list[str],
        dual: list[float] | Arr1dF64,
        dual2: list[float] | Arr1dF64,
    ) -> Dual2: ...
    def grad1_manifold(self, vars: Sequence[str]) -> list[Dual2]: ...
    def to_dual(self) -> Dual: ...

def _dsolve1(a: list[Any], b: list[Any], allow_lsq: bool) -> list[Dual]: ...
def _dsolve2(a: list[Any], b: list[Any], allow_lsq: bool) -> list[Dual2]: ...
def _fdsolve1(a: Arr2dF64, b: list[Any], allow_lsq: bool) -> list[Dual]: ...
def _fdsolve2(a: Arr2dF64, b: list[Any], allow_lsq: bool) -> list[Dual2]: ...

class PPSplineF64:
    n: int = ...
    k: int = ...
    t: list[float] = ...
    c: list[float] | None = ...
    def __init__(self, k: int, t: list[float], c: list[float] | None) -> None: ...
    def csolve(
        self, tau: list[float], y: list[float], left_n: int, right_n: int, allow_lsq: bool
    ) -> None: ...
    def ppev_single(self, x: Number) -> float: ...
    def ppev_single_dual(self, x: Number) -> Dual: ...
    def ppev_single_dual2(self, x: Number) -> Dual2: ...
    def ppev(self, x: list[float]) -> list[float]: ...
    def ppdnev_single(self, x: Number, m: int) -> float: ...
    def ppdnev_single_dual(self, x: Number, m: int) -> Dual: ...
    def ppdnev_single_dual2(self, x: Number, m: int) -> Dual2: ...
    def ppdnev(self, x: list[float], m: int) -> list[float]: ...
    def bsplev(self, x: list[float], i: int) -> list[float]: ...
    def bspldnev(self, x: list[float], i: int, m: int) -> list[float]: ...
    def bsplmatrix(self, tau: list[float], left_n: int, right_n: int) -> Arr2dF64: ...
    def __eq__(self, other: PPSplineF64) -> bool: ...  # type: ignore[override]
    def __copy__(self) -> PPSplineF64: ...
    def to_json(self) -> str: ...

class PPSplineDual:
    n: int = ...
    k: int = ...
    t: list[float] = ...
    c: list[Dual] | None = ...
    def __init__(self, k: int, t: list[float], c: list[Dual] | None) -> None: ...
    def csolve(
        self, tau: list[float], y: list[Dual], left_n: int, right_n: int, allow_lsq: bool
    ) -> None: ...
    def ppev_single(self, x: Number) -> Dual: ...
    def ppev_single_dual(self, x: Number) -> Dual: ...
    def ppev_single_dual2(self, x: Number) -> Dual2: ...
    def ppev(self, x: list[float]) -> list[Dual]: ...
    def ppdnev_single(self, x: Number, m: int) -> Dual: ...
    def ppdnev_single_dual(self, x: Number, m: int) -> Dual: ...
    def ppdnev_single_dual2(self, x: Number, m: int) -> Dual2: ...
    def ppdnev(self, x: list[float], m: int) -> list[Dual]: ...
    def bsplev(self, x: list[float], i: int) -> list[Dual]: ...
    def bspldnev(self, x: list[float], i: int, m: int) -> list[Dual]: ...
    def bsplmatrix(self, tau: list[float], left_n: int, right_n: int) -> Arr2dF64: ...
    def __eq__(self, other: PPSplineDual) -> bool: ...  # type: ignore[override]
    def __copy__(self) -> PPSplineDual: ...
    def to_json(self) -> str: ...

class PPSplineDual2:
    n: int = ...
    k: int = ...
    t: list[float] = ...
    c: list[Dual2] | None = ...
    def __init__(self, k: int, t: list[float], c: list[Dual2] | None) -> None: ...
    def csolve(
        self, tau: list[float], y: list[Dual2], left_n: int, right_n: int, allow_lsq: bool
    ) -> None: ...
    def ppev_single(self, x: Number) -> Dual2: ...
    def ppev_single_dual(self, x: Number) -> Dual: ...
    def ppev_single_dual2(self, x: Number) -> Dual2: ...
    def ppev(self, x: list[float]) -> list[Dual2]: ...
    def ppdnev_single(self, x: Number, m: int) -> Dual2: ...
    def ppdnev_single_dual(self, x: Number, m: int) -> Dual: ...
    def ppdnev_single_dual2(self, x: Number, m: int) -> Dual2: ...
    def ppdnev(self, x: list[float], m: int) -> list[Dual2]: ...
    def bsplev(self, x: list[float], i: int) -> list[Dual2]: ...
    def bspldnev(self, x: list[float], i: int, m: int) -> list[Dual2]: ...
    def bsplmatrix(self, tau: list[float], left_n: int, right_n: int) -> Arr2dF64: ...
    def __eq__(self, other: PPSplineDual2) -> bool: ...  # type: ignore[override]
    def __copy__(self) -> PPSplineDual2: ...
    def to_json(self) -> str: ...

def bsplev_single(x: float, i: int, k: int, t: list[float], org_k: int | None) -> float: ...
def bspldnev_single(
    x: float, i: int, k: int, t: list[float], m: int, org_k: int | None
) -> float: ...
def from_json(json: str) -> Any: ...

class FlatBackwardInterpolator:
    def __init__(self) -> None: ...

class FlatForwardInterpolator:
    def __init__(self) -> None: ...

class LinearInterpolator:
    def __init__(self) -> None: ...

class LogLinearInterpolator:
    def __init__(self) -> None: ...

class LinearZeroRateInterpolator:
    def __init__(self) -> None: ...

class NullInterpolator:
    def __init__(self) -> None: ...

class Curve:
    modifier: Modifier = ...
    convention: Convention = ...
    interpolation: str = ...
    ad: ADOrder = ...
    id: str = ...
    nodes: dict[datetime, Number] = ...
    def __init__(
        self,
        nodes: dict[datetime, Number],
        interpolator: CurveInterpolator,
        ad: ADOrder,
        id: str,
        convention: Convention,
        modifier: Modifier,
        calendar: CalTypes,
        index_base: float | None,
    ) -> None: ...
    def to_json(self) -> str: ...
    def __eq__(self, other: Curve) -> bool: ...  # type: ignore[override]
    def __getitem__(self, date: datetime) -> Number: ...
    def set_ad_order(self, ad: ADOrder) -> None: ...
    def index_value(self, date: datetime) -> Number: ...

def _get_convention_str(convention: Convention) -> str: ...
def _get_modifier_str(modifier: Modifier) -> str: ...

def index_left_f64(list_input: list[float], value: float, left_count: int | None) -> int: ...
