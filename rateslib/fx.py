from typing import Any, Optional, Union
import numpy as np
from pandas import DataFrame, Series
from pandas.tseries.offsets import CustomBusinessDay
from itertools import product
import warnings
from datetime import timedelta, datetime
import json

from rateslib import defaults
from rateslib.dual import Dual, dual_solve, set_order
from rateslib.defaults import plot
from rateslib.calendars import add_tenor
from rateslib.curves import Curve, LineCurve
"""
.. ipython:: python
   :suppress:

   from rateslib.curves import Curve
   from datetime import datetime as dt
"""


# Licence: Creative Commons - Attribution-NonCommercial-NoDerivatives 4.0 International
# Commercial use of this code, and/or copying and redistribution is prohibited.
# Contact rateslib at gmail.com if this code is observed outside its intended sphere.

class FXRates:
    """
    Object to store and calculate FX rates for a consistent settlement date.

    Parameters
    ----------
    fx_rates : dict
        Dict whose keys are 6-character domestic-foreign currency pairs, and whose
        values are the relevant rates.
    settlement : datetime, optional
        The settlement date for the FX rates.
    base : str, optional
        The base currency (3-digit code). If not given defaults to either:

          - the default base currency, if it is present in the list of currencies,
          - the first currency detected.

    Notes
    -----

    .. note::
       When this class uses ``Dual`` numbers to represent sensitivities of values to
       certain FX rates the variable names are called `"fx_domfor"` where `"dom"`
       is a domestic currency and `"for"` is a foreign currency. See the examples
       contained in class methods for clarification.

    Examples
    --------
    An FX rates market of *n* currencies is completely defined by *n-1*
    independent FX pairs.

    Below we define an FX rates market in 4 currencies with 3 FX pairs,

    .. ipython:: python

       fxr = FXRates({"eurusd": 1.1, "gbpusd": 1.25, "usdjpy": 100})
       fxr.currencies
       fxr.rate("gbpjpy")

    Ill defined FX markets will raise ``ValueError`` and are either **overspecified**,

    .. ipython:: python

       try:
           FXRates({"eurusd": 1.1, "gbpusd": 1.25, "usdjpy": 100, "gbpjpy": 125})
       except ValueError as e:
           print(e)

    or are **underspecified**,

    .. ipython:: python

       try:
           FXRates({"eurusd": 1.1, "gbpjpy": 125})
       except ValueError as e:
           print(e)

    or use redundant, co-dependent information,

    .. ipython:: python

       try:
           FXRates({"eurusd": 1.1, "usdeur": 0.90909, "gbpjpy": 125})
       except ValueError as e:
           print(e)

    Attributes
    ----------
    pairs : list
    settlement : datetime
    currencies : dict
    currencies_list : list
    q : int
    fx_rates : dict
    fx_vector : ndarray
    fx_array : ndarray
    """

    def __init__(
        self,
        fx_rates: dict,
        settlement: Optional[datetime] = None,
        base: Optional[str] = None
    ):
        self._ad = 1
        self.settlement = settlement

        # covert all str to lowercase and values to Dual
        def _convert_dual(k, v):
            if isinstance(v, Dual):
                return v
            return Dual(v, f"fx_{k.lower()}")
        self.fx_rates = {
            k.lower(): _convert_dual(k, v) for k, v in fx_rates.items()
        }

        # find currencies
        self.pairs = [k for k in self.fx_rates.keys()]
        self.variables = tuple(f"fx_{pair}" for pair in self.pairs)
        self.currencies = {
            k: i for i, k in enumerate(list(
            dict.fromkeys([p[:3] for p in self.pairs] + [p[3:6] for p in self.pairs])
        ))
        }
        self.currencies_list = list(self.currencies.keys())
        if base is None:
            if defaults.base_currency in self.currencies_list:
                self.base = defaults.base_currency
            else:
                self.base = self.currencies_list[0]
        else:
            self.base = base.lower()
        self.q = len(self.currencies)
        if len(self.pairs) > (self.q - 1):
            raise ValueError(
                f"`fx_rates` is overspecified: {self.q} currencies needs "
                f"{self.q-1} FX pairs, not {len(self.pairs)}."
            )
        elif len(self.pairs) < (self.q - 1):
            raise ValueError(
                f"`fx_rates` is underspecified: {self.q} currencies needs "
                f"{self.q - 1} FX pairs, not {len(self.pairs)}."
            )

        # solve FX vector in linear system
        A = np.zeros((self.q, self.q), dtype="object")
        b = np.ones(self.q, dtype="object")
        A[0, 0] = 1.0
        for i, pair in enumerate(self.pairs):
            domestic_idx = self.currencies[pair[:3]]
            foreign_idx = self.currencies[pair[3:]]
            A[i+1, domestic_idx] = -1.0
            A[i+1, foreign_idx] = 1 / self.fx_rates[pair]
            b[i+1] = 0
        x = dual_solve(A, b[:, np.newaxis])[:, 0]
        self.fx_vector = x

        # solve fx_rates array
        self.fx_array = np.eye(self.q, dtype="object")
        for i in range(self.q):
            for j in range(i+1, self.q):
                self.fx_array[i, j], self.fx_array[j, i] = x[j] / x[i], x[i] / x[j]

    def restate(self, pairs: list[str], keep_ad: bool = False):
        """
        Recreate an :class:`FXRates` class using other, derived currency pairs.

        This will redefine the pairs to which delta risks are expressed in ``Dual``
        outputs. If ``pairs`` match the existing object and ``keep_ad`` is
        requested then the existing object is returned unchanged.

        Parameters
        ----------
        pairs : list of str
            The new currency pairs with which to define the ``FXRates`` class.
        keep_ad : bool, optional
            Keep the original derivative exposures defined by ``Dual``, instead
            of redefinition.

        Returns
        --------
        FXRates

        Examples
        --------

        .. ipython:: python

           fxr = FXRates({"eurgbp": 0.9, "gbpjpy": 125, "usdjpy": 100})
           fxr.convert(100, "gbp", "usd")
           fxr2 = fxr.restate(["eurusd", "gbpusd", "usdjpy"])
           fxr2.convert(100, "gbp", "usd")
        """
        if set(pairs) == set(self.pairs) and keep_ad:
            return self.copy()  # no restate needed but return new instance

        restated_fx_rates = FXRates(
            {pair: self.rate(pair) if keep_ad else self.rate(pair).real
             for pair in pairs},
            self.settlement
        )
        return restated_fx_rates

    def convert(
        self,
        value: Union[Dual, float],
        domestic: str,
        foreign: Optional[str] = None,
        on_error: str = "ignore"
    ):
        """
        Convert an amount of a domestic currency into a foreign currency.

        Parameters
        ----------
        value : float or Dual
            The amount of the domestic currency to convert.
        domestic : str
            The domestic currency (3-digit code).
        foreign : str, optional
            The foreign currency to convert to (3-digit code). Uses instance
            ``base`` if not given.
        on_error : str in {"ignore", "warn", "raise"}
            The action taken if either ``domestic`` or ``foreign`` are not contained
            in the FX framework. `"ignore"` and `"warn"` will still return `None`.

        Returns
        -------
        Dual or None

        Examples
        --------

        .. ipython:: python

           fxr = FXRates({"usdnok": 8.0})
           fxr.convert(1000000, "nok", "usd")
           fxr.convert(1000000, "nok", "inr")  # <- returns None, "inr" not in fxr.

        """
        foreign = self.base if foreign is None else foreign.lower()
        domestic = domestic.lower()
        for ccy in [domestic, foreign]:
            if ccy not in self.currencies:
                if on_error == "ignore":
                    return None
                elif on_error == "warn":
                    warnings.warn(
                        f"'{ccy}' not in FXRates.currencies: returning None.",
                        UserWarning
                    )
                    return None
                else:
                    raise ValueError(f"'{ccy}' not in FXRates.currencies.")

        i, j = self.currencies[domestic.lower()], self.currencies[foreign.lower()]
        return value * self.fx_array[i, j]

    def convert_positions(
        self,
        array: Union[np.array, list],
        base: Optional[str] = None,
    ):
        """
        Convert an array of currency cash positions into a single base currency.

        Parameters
        ----------
        array : list, 1d ndarray of floats, or Series
            The cash positions to simultaneously convert in the base currency. **Must**
            be ordered by currency as defined in the attribute ``FXRates.currencies``.
        base : str, optional
            The currency to convert to (3-digit code). Uses instance ``base`` if not
            given.

        Returns
        -------
        Dual

        Examples
        --------

        .. ipython:: python

           fxr = FXRates({"usdnok": 8.0})
           fxr.currencies
           fxr.convert_positions([0, 1000000], "usd")
        """
        base = self.base if base is None else base.lower()
        array_ = np.asarray(array)
        j = self.currencies[base]
        return np.sum(array_ * self.fx_array[:, j])

    def positions(
        self,
        value,
        base: Optional[str] = None,
    ):
        """
        Convert a base value with FX rate sensitivities into an array of cash positions.

        Parameters
        ----------
        value : float or Dual
            The amount expressed in base currency to convert to cash positions.
        base : str, optional
            The base currency in which ``value`` is given (3-digit code). If *None*
            assumes the ``base`` of the object.

        Returns
        -------
        Series

        Examples
        --------
        .. ipython:: python

           fxr = FXRates({"usdnok": 8.0})
           fxr.positions(Dual(125000, "fx_usdnok", np.array([-15625])), "usd")
           fxr.positions(100, base="nok")

        """
        if isinstance(value, (float, int)):
            value = Dual(value)
        base = self.base if base is None else base.lower()
        _ = np.array(
            [0 if ccy != base else float(value) for ccy in self.currencies_list]
        )
        for pair in value.vars:
            if pair[:3] == "fx_":
                delta = value.gradient(pair)[0]
                _ += self._get_positions_from_delta(delta, pair[3:], base)
        return Series(_, index=self.currencies_list)

    def _get_positions_from_delta(
        self,
        delta: float,
        pair: str,
        base: str
    ):
        """Return an array of cash positions determined from an FX pair delta risk."""
        b_idx = self.currencies[base]
        domestic, foreign = pair[:3], pair[3:]
        d_idx, f_idx = self.currencies[domestic], self.currencies[foreign]
        _ = np.zeros(self.q)

        # f_val = -delta * float(self.fx_array[b_idx, d_idx]) * float(self.fx_array[d_idx, f_idx])**2
        # _[f_idx] = f_val
        # _[d_idx] = -f_val / float(self.fx_array[d_idx, f_idx])
        # return _
        f_val = delta * float(self.fx_array[b_idx, f_idx])
        _[d_idx] = f_val
        _[f_idx] = -f_val / float(self.fx_array[f_idx, d_idx])
        return _  # calculation is more efficient from a domestic pov than foreign

    def rate(self, pair: str):
        """
        Return a specified FX rate for a given currency pair.

        Parameters
        ----------
        pair : str
            The FX pair in usual domestic:foreign convention (6 digit code).

        Returns
        -------
        Dual

        Examples
        --------

        .. ipython:: python

           fxr = FXRates({"usdeur": 2.0, "usdgbp": 2.5})
           fxr.rate("eurgbp")
        """
        domestic, foreign = pair[:3].lower(), pair[3:].lower()
        return self.fx_array[self.currencies[domestic], self.currencies[foreign]]

    def rates_table(self):
        """
        Return a DataFrame of all FX rates in the object.

        Returns
        -------
        DataFrame
        """
        return DataFrame(
            np.vectorize(float)(self.fx_array),
            index=self.currencies_list,
            columns=self.currencies_list,
        )

    def update(self, fx_rates: dict):
        """
        Update all or some of the FX rates of the instance.

        Parameters
        ----------
        fx_rates : dict
            Dict whose keys are 6-character domestic-foreign currency pairs and
            which are present in FXRates.pairs, and whose
            values are the relevant rates to update.

        Returns
        -------
        None

        Notes
        -----

        .. warning::

           **Rateslib** is an object-oriented library that uses complex associations. It
           is best practice to create objects and any associations and then use the
           ``update`` methods to push new market data to them. Recreating objects with
           new data will break object-oriented associations and possibly lead to
           undetected market data based pricing errors.

        Do **not** do this..

        .. ipython:: python

           fxr = FXRates({"eurusd": 1.05}, settlement=dt(2022, 1, 3), base="usd")
           fx_curves = {
               "usdusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.965}),
               "eureur": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
               "eurusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
           }
           fxf = FXForwards(fxr, fx_curves)
           id(fxr) == id(fxf.fx_rates)  #  <- these objects are associated
           fxr = FXRates({"eurusd": 1.06}, settlement=dt(2022, 1, 3), base="usd")
           id(fxr) == id(fxf.fx_rates)  #  <- this association is broken by new instance
           fxf.rate("eurusd", dt(2022, 1, 3))  # <- wrong price because it is broken

        Instead **do this**..

        .. ipython:: python

           fxr = FXRates({"eurusd": 1.05}, settlement=dt(2022, 1, 3), base="usd")
           fx_curves = {
               "usdusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.965}),
               "eureur": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
               "eurusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
           }
           fxf = FXForwards(fxr, fx_curves)
           fxr.update({"eurusd": 1.06})
           fxf.update()
           id(fxr) == id(fxf.fx_rates)  #  <- this association is maintained
           fxf.rate("eurusd", dt(2022, 1, 3))  # <- correct new price

        Examples
        --------

        .. ipython:: python

           fxr = FXRates({"usdeur": 0.9, "eurnok": 8.5})
           fxr.rate("usdnok")
           fxr.update({"usdeur": 1.0})
           fxr.rate("usdnok")
        """
        fx_rates_ = {k.lower(): v for k, v in fx_rates.items()}
        pairs = list(fx_rates_.keys())
        if len(set(pairs).difference(set(self.pairs))) != 0:
            raise ValueError("`fx_rates` must contain the same pairs as the instance.")
        fx_rates_ = {
            pair: float(self.fx_rates[pair]) if pair not in pairs else fx_rates_[pair]
            for pair in self.pairs
        }
        _ = FXRates(fx_rates_, settlement=self.settlement, base=self.base)
        for attr in ["fx_rates", "fx_vector", "fx_array"]:
            setattr(self, attr, getattr(_, attr))

    def _set_ad_order(self, order):
        """
        Change the node values to float, Dual or Dual2 based on input parameter.
        """
        if order == getattr(self, "_ad", None):
            return None
        if order not in [0, 1, 2]:
            raise ValueError("`order` can only be in {0, 1, 2} for auto diff calcs.")

        self._ad = order
        self.fx_vector = np.array([set_order(v, order) for v in self.fx_vector])
        x = self.fx_vector
        # solve fx_rates array
        self.fx_array = np.eye(self.q, dtype="object")
        for i in range(self.q):
            for j in range(i+1, self.q):
                self.fx_array[i, j], self.fx_array[j, i] = x[j] / x[i], x[i] / x[j]
        for k, v in self.fx_rates.items():
            self.fx_rates[k] = set_order(v, order)

        return None

    def to_json(self):
        """
        Convert FXRates object to a JSON string.

        This is usually a precursor to storing objects in a database, or transmitting
        via an API across platforms, e.g. webservers or to Excel, for example.

        Returns
        -------
        str

        Examples
        --------
        .. ipython:: python

           fxr = FXRates({"eurusd": 1.05}, base="EUR")
           fxr.to_json()
        """
        if self.settlement is None:
            settlement = None
        else:
            settlement = self.settlement.strftime("%Y-%m-%d")
        container = {
            "fx_rates": {k: float(v) for k, v in self.fx_rates.items()},
            "settlement": settlement,
            "base": self.base,
        }
        return json.dumps(container, default=str)

# Licence: Creative Commons - Attribution-NonCommercial-NoDerivatives 4.0 International
# Commercial use of this code, and/or copying and redistribution is prohibited.
# Contact rateslib at gmail.com if this code is observed outside its intended sphere.

    @classmethod
    def from_json(cls, fx_rates, **kwargs):
        """
        Load an FXRates object from a JSON string.

        This is usually required if a saved or transmitted object is to be recovered
        from a database or API.

        Parameters
        ----------
        fx_rates : str
             The JSON string of the underlying FXRates object to be reconstructed.

        Returns
        -------
        FXRates

        Examples
        --------
        .. ipython:: python

           json = '{"fx_rates": {"eurusd": 1.05}, "settlement": null, "base": "eur"}'
           fxr = FXRates.from_json(json)
           fxr.rates_table()
        """
        serial = json.loads(fx_rates)
        if isinstance(serial["settlement"], str):
            serial["settlement"] = datetime.strptime(serial["settlement"], "%Y-%m-%d")
        return FXRates(**{**serial, **kwargs})

    def __eq__(self, other):
        """Test two FXRates are identical"""
        if type(self) != type(other):
            return False
        for attr in [
            "pairs",
            "settlement",
            "currencies_list",
            "base",
        ]:
            if getattr(self, attr, None) != getattr(other, attr, None):
                return False
        if not np.all(np.isclose(self.rates_table(), other.rates_table())):
            return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def copy(self):
        return FXRates(
            fx_rates=self.fx_rates.copy(),
            settlement=self.settlement,
            base=self.base
        )


class FXForwards:
    """
    Class for storing and calculating FX forward rates.

    Parameters
    ----------
    fx_rates : FXRates, or list of such
        An ``FXRates`` object with an associated settlement date. If multiple settlement
        dates are relevant, e.g. GBPUSD (T+2) and USDCAD(T+1), then a list of
        ``FXRates`` object is allowed to create a no arbitrage framework.
    fx_curves : dict
        A dict of DF ``Curve`` objects defined by keys of two currency labels. First, by
        the currency in which cashflows occur (3-digit code), combined with the
        currency by which the future cashflow is collateralised in a derivatives sense
        (3-digit code). There must also be a curve in each currency for
        local discounting, i.e. where the cashflow and collateral currency are the
        same. See examples.
    base : str, optional
        The base currency (3-digit code). If not given defaults to the base currency
        of the first ``fx_rates`` object.

    Notes
    -----

    .. math::

       f_{DOMFOR,i} &= \\text{Forward domestic-foreign FX rate fixing on maturity date, }m_i \\\\
       F_{DOMFOR,0} &= \\text{Immediate settlement market domestic-foreign FX rate} \\\\
       v_{dom:dom,i} &= \\text{Local domestic-currency DF on maturity date, }m_i \\\\
       w_{dom:for,i} &= \\text{XCS adjusted domestic-currency DF on maturity date, }m_i \\\\

    Examples
    --------
    The most basic ``FXForwards`` object is created from a spot ``FXRates`` object and
    two local currency discount curves.

    .. ipython:: python

       from rateslib.fx import FXRates, FXForwards
       from rateslib.curves import Curve

    .. ipython:: python

       fxr = FXRates({"eurusd": 1.1}, settlement=dt(2022, 1, 3))
       eur_local = Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.91})
       usd_local = Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.95})
       fxf = FXForwards(fxr, {"usdusd": usd_local, "eureur": eur_local, "eurusd": eur_local})

    Note that in the above the ``eur_local`` curve has also been used as the curve
    for EUR cashflows collateralised in USD, which is necessary for calculation
    of forward FX rates and cross-currency basis. With this assumption the
    cross-currency basis is implied to be zero at all points along the curve.

    Attributes
    ----------
    fx_rates : FXRates or list
    fx_curves : dict
    immediate : datetime
    currencies: dict
    q : int
    currencies_list : list
    transform : ndarray
    base : str
    fx_rates_immediate : FXRates
    """
    def update(
        self,
        fx_rates: Optional[Union[FXRates, list[FXRates]]] = None,
        fx_curves: Optional[dict] = None,
        base: Optional[str] = None,
    ):
        """
        Update the FXForward object with the latest FX rates and FX curves values.

        The update method is primarily used to allow synchronous updating within a
        ``Solver``.

        Parameters
        ----------
        fx_rates : FXRates, or list of such, optional
            An ``FXRates`` object with an associated settlement date. If multiple
            settlement dates are relevant, e.g. GBPUSD (T+2) and USDCAD(T+1), then a
            list of ``FXRates`` object is allowed to create a no arbitrage framework.
        fx_curves : dict, optional
            A dict of DF ``Curve`` objects defined by keys of two currency labels.
            First, by the currency in which cashflows occur (3-digit code), combined
            with the currency by which the future cashflow is collateralised in a
            derivatives sense (3-digit code). There must also be a curve in each
            currency for local discounting, i.e. where the cashflow and collateral
            currency are the same. See examples of instance instantiation.
        base : str, optional
            The base currency (3-digit code). If not given defaults to the base
            currency of the first given ``fx_rates`` object.

        Returns
        -------
        None

        Notes
        -----
        .. warning::

           **Rateslib** is an object-oriented library that uses complex associations. It
           is best practice to create objects and any associations and then use the
           ``update`` methods to push new market data to them. Recreating objects with
           new data will break object-oriented associations and possibly lead to
           undetected market data based pricing errors.

        Do **not** do this..

        .. ipython:: python

           fxr = FXRates({"eurusd": 1.05}, settlement=dt(2022, 1, 3), base="usd")
           fx_curves = {
               "usdusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.965}),
               "eureur": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
               "eurusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
           }
           fxf = FXForwards(fxr, fx_curves)
           id(fxr) == id(fxf.fx_rates)  #  <- these objects are associated
           fxr = FXRates({"eurusd": 1.06}, settlement=dt(2022, 1, 3), base="usd")
           id(fxr) == id(fxf.fx_rates)  #  <- this association is broken by new instance
           fxf.rate("eurusd", dt(2022, 1, 3))  # <- wrong price because it is broken

        Instead **do this**..

        .. ipython:: python

           fxr = FXRates({"eurusd": 1.05}, settlement=dt(2022, 1, 3), base="usd")
           fx_curves = {
               "usdusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.965}),
               "eureur": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
               "eurusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.985}),
           }
           fxf = FXForwards(fxr, fx_curves)
           fxr.update({"eurusd": 1.06})
           fxf.update()
           id(fxr) == id(fxf.fx_rates)  #  <- this association is maintained
           fxf.rate("eurusd", dt(2022, 1, 3))  # <- correct new price

        For regular use, an ``FXForwards`` class has its associations, with ``FXRates``
        and ``Curve`` s, set at instantiation. This means that the most common
        form of this method will be to call it with no new arguments, but after
        either one of the ``FXRates`` or ``Curve`` objects has itself been updated.

        Examples
        --------
        Updating a component ``FXRates`` instance before updating the ``FXForwards``.

        .. ipython:: python

           uu_curve = Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.96}, id="uu")
           fx_curves = {
               "usdusd": uu_curve,
               "eureur": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.99}, id="ee"),
               "eurusd": Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.991}, id="eu"),
           }
           fx_rates = FXRates({"usdeur": 0.9}, dt(2022, 1, 3))
           fxf = FXForwards(fx_rates, fx_curves)
           fxf.rate("usdeur", dt(2022, 7, 15))
           fx_rates.update({"usdeur": 1.0})
           fxf.update()
           fxf.rate("usdeur", dt(2022, 7, 15))

        Updating an ``FXForwards`` instance with a new ``FXRates`` instance.

        .. ipython:: python

           fxf = FXForwards(FXRates({"usdeur": 0.9}, dt(2022, 1, 3)), fx_curves)
           fxf.update(FXRates({"usdeur": 1.0}, dt(2022, 1, 3)))
           fxf.rate("usdeur", dt(2022, 7, 15))

        Updating a ``Curve`` component before updating the ``FXForwards``.

        .. ipython:: python

           fxf = FXForwards(FXRates({"usdeur": 0.9}, dt(2022, 1, 3)), fx_curves)
           uu_curve.nodes[dt(2023, 1, 1)] = 0.98
           fxf.update()
           fxf.rate("usdeur", dt(2022, 7, 15))

        """
        if isinstance(fx_curves, dict):
            self.fx_curves = {k.lower(): v for k, v in fx_curves.items()}

            self.immediate = None
            self.terminal = datetime(2200, 1, 1)
            for _, curve in self.fx_curves.items():
                if self.immediate is None:
                    self.immediate = curve.node_dates[0]
                elif self.immediate != curve.node_dates[0]:
                    raise ValueError("`fx_curves` do not have the same initial date.")
                if isinstance(curve, LineCurve):
                    raise TypeError("`fx_curves` must be DF based, not type LineCurve.")
                if curve.node_dates[-1] < self.terminal:
                    self.terminal = curve.node_dates[-1]

        if fx_rates is not None:
            self.fx_rates = fx_rates

        if isinstance(self.fx_rates, list):
            acyclic_fxf = None
            for fx_rates_obj in self.fx_rates:
                # create sub FXForwards for each FXRates instance and re-combine.
                # This reuses the arg validation of a single FXRates object and
                # dependency of FXRates with fx_curves.
                if acyclic_fxf is None:
                    sub_curves = self._get_curves_for_currencies(
                        self.fx_curves, fx_rates_obj.currencies_list
                    )
                    acyclic_fxf = FXForwards(
                        fx_rates=fx_rates_obj,
                        fx_curves=sub_curves,
                    )
                else:
                    # calculate additional FX rates from previous objects
                    # in the same settlement frame.
                    pre_currencies = [
                        ccy for ccy in acyclic_fxf.currencies_list
                        if ccy not in fx_rates_obj.currencies_list
                    ]
                    pre_rates = {
                        f"{fx_rates_obj.base}{ccy}": acyclic_fxf.rate(
                            f"{fx_rates_obj.base}{ccy}", fx_rates_obj.settlement
                        )
                        for ccy in pre_currencies
                    }
                    combined_fx_rates = FXRates(
                        fx_rates={**fx_rates_obj.fx_rates, **pre_rates},
                        settlement=fx_rates_obj.settlement
                    )
                    sub_curves = self._get_curves_for_currencies(
                        self.fx_curves, fx_rates_obj.currencies_list + pre_currencies
                    )
                    acyclic_fxf = FXForwards(
                        fx_rates=combined_fx_rates,
                        fx_curves=sub_curves
                    )

            if base is not None:
                acyclic_fxf.base = base.lower()

            for attr in [
                "currencies",
                "q",
                "currencies_list",
                "transform",
                "base",
                "fx_rates_immediate",
                "pairs",
            ]:
                setattr(self, attr, getattr(acyclic_fxf, attr))
        else:
            self.currencies = self.fx_rates.currencies
            self.q = len(self.currencies.keys())
            self.currencies_list = list(self.currencies.keys())
            self.transform = self._get_forwards_transformation_matrix(
                self.q, self.currencies, self.fx_curves
            )
            self.base = self.fx_rates.base if base is None else base
            self.pairs = self.fx_rates.pairs
            self.variables = tuple(f"fx_{pair}" for pair in self.pairs)
            self.fx_rates_immediate = self._update_fx_rates_immediate()

    def __init__(
        self,
        fx_rates: Union[FXRates, list[FXRates]],
        fx_curves: dict,
        base: Optional[str] = None,
    ):
        self._ad = 1
        self.update(fx_rates, fx_curves, base)

    @staticmethod
    def _get_curves_for_currencies(fx_curves, currencies):
        ps = product(currencies, currencies)
        ret = {p[0]+p[1]: fx_curves[p[0]+p[1]] for p in ps if p[0]+p[1] in fx_curves}
        return ret

    @staticmethod
    def _get_forwards_transformation_matrix(q, currencies, fx_curves):
        """
        Performs checks to ensure FX forwards can be generated from provided DF curves.

        The transformation matrix has cash currencies by row and collateral currencies
        by column.
        """
        # Define the transformation matrix with unit elements in each valid pair.
        T = np.zeros((q, q))
        for k, _ in fx_curves.items():
            cash, coll = k[:3].lower(), k[3:].lower()
            try:
                cash_idx, coll_idx = currencies[cash], currencies[coll]
            except KeyError:
                raise ValueError(
                    f"`fx_curves` contains an unexpected currency: {cash} or {coll}"
                )
            T[cash_idx, coll_idx] = 1

        if T.sum() > (2 * q) - 1:
            raise ValueError(
                f"`fx_curves` is overspecified. {2 * q - 1} curves are expected "
                f"but {len(fx_curves.keys())} provided."
            )
        elif T.sum() < (2 * q) - 1:
            raise ValueError(
                f"`fx_curves` is underspecified. {2 * q -1} curves are expected "
                f"but {len(fx_curves.keys())} provided."
            )
        elif np.linalg.matrix_rank(T) != q:
            raise ValueError("`fx_curves` contains co-dependent rates.")
        return T

    @staticmethod
    def _get_recursive_chain(
        T: np.ndarray,
        start_idx: int,
        search_idx: int,
        traced_paths: list[int] = [],
        recursive_path: list[dict] = [],
    ):
        """
        Recursively calculate map from a cash currency to another via collateral curves.

        Parameters
        ----------
        T : ndarray
            The transformation mapping of cash and collateral currencies.
        start_idx : int
            The index of the currency as the starting point of this search.
        search_idx : int
            The index of the currency identifying the termination of search.
        traced_paths : list[int]
            The index of currencies that have already been exhausted within the search.
        recursive_path : list[dict]
            The path taken from the original start to the current search start location.

        Returns
        -------
        bool, path

        Notes
        -----
        The return path outlines the route taken from the ``start_idx`` to the
        ``search_idx`` detailing each step as either traversing a row or column.

        Examples
        --------
        .. ipython:: python

           T = np.array([[1,1,1,0], [0,1,0,1],[0,0,1,0],[0,0,0,1]])
           FXForwards._get_recursive_chain(T, 0, 3)

        """
        recursive_path = recursive_path.copy()
        traced_paths = traced_paths.copy()
        if len(traced_paths) == 0:
            traced_paths.append(start_idx)

        # try row:
        row_paths = np.where(T[start_idx, :] == 1)[0]
        col_paths = np.where(T[:, start_idx] == 1)[0]
        if search_idx in row_paths:
            recursive_path.append({"row": search_idx})
            return True, recursive_path
        if search_idx in col_paths:
            recursive_path.append({"col": search_idx})
            return True, recursive_path

        for (axis, paths) in [("row", row_paths), ("col", col_paths)]:
            for path_idx in paths:
                if path_idx == start_idx:
                    pass
                elif path_idx != search_idx and path_idx not in traced_paths:
                    recursive_path_app = recursive_path + [{axis: path_idx}]
                    traced_paths_app = traced_paths + [path_idx]
                    recursion = FXForwards._get_recursive_chain(
                        T, path_idx, search_idx, traced_paths_app, recursive_path_app
                    )
                    if recursion[0]:
                        return recursion

        return False, recursive_path

# Licence: Creative Commons - Attribution-NonCommercial-NoDerivatives 4.0 International
# Commercial use of this code, and/or copying and redistribution is prohibited.
# Contact rateslib at gmail.com if this code is observed outside its intended sphere.

    def _update_fx_rates_immediate(self):
        """
        Find the immediate FX rates values.

        Notes
        -----
        Searches the non-diagonal elements of transformation matrix, once it has
        found a pair uses the relevant curves and the FX rate to determine the
        immediate FX rate for that pair.
        """
        fx_rates_immediate = {}
        for row in range(self.q):
            for col in range(self.q):
                if row == col or self.transform[row, col] == 0:
                    continue
                cash_ccy = self.currencies_list[row]
                coll_ccy = self.currencies_list[col]
                settlement = self.fx_rates.settlement
                v_i = self.fx_curves[f"{coll_ccy}{coll_ccy}"][settlement]
                w_i = self.fx_curves[f"{cash_ccy}{coll_ccy}"][settlement]
                pair = f"{cash_ccy}{coll_ccy}"
                fx_rates_immediate.update({
                   pair: self.fx_rates.fx_array[row, col] * v_i / w_i
                })

        fx_rates_immediate = FXRates(fx_rates_immediate, self.immediate)
        return fx_rates_immediate.restate(self.fx_rates.pairs, keep_ad=True)

    def rate(
        self,
        pair: str,
        settlement: Optional[datetime] = None,
        path: Optional[list[dict]] = None,
        return_path: bool = False,
    ):
        """
        Return the fx forward rate for a currency pair.

        Parameters
        ----------
        pair : str
            The FX pair in usual domestic:foreign convention (6 digit code).
        settlement : datetime, optional
            The settlement date of currency exchange. If `None` defaults to
            immediate settlement.
        path : list of dict, optional
            The chain of currency collateral curves to traverse to calculate the rate.
            This is calculated automatically and this argument is provided for
            internal calculation to avoid repeatedly calculating the same path. Use of
            this argument in normal circumstances is not recommended.
        return_path : bool
            If `True` returns the path in a tuple alongside the rate. Use of this
            argument in normal circumstances is not recommended.

        Returns
        -------
        float, Dual, Dual2 or tuple

        Notes
        -----
        Uses the formula,

        .. math::

           f_{DOMFOR, i} = \\frac{w_{dom:for, i}}{v_{for:for, i}} F_{DOMFOR,0} = \\frac{v_{dom:dom, i}}{w_{for:dom, i}} F_{DOMFOR,0}

        where :math:`v` is a local currency discount curve and :math:`w` is a discount
        curve collateralised with an alternate currency.

        Where curves do not exist in the relevant currencies we chain rates available
        given the available curves.

        .. math::

           f_{DOMFOR, i} = f_{DOMALT, i} ...  f_{ALTFOR, i}

        """
        def _get_d_f_idx_and_path(pair, path: dict):
            domestic, foreign = pair[:3].lower(), pair[3:].lower()
            d_idx = self.fx_rates_immediate.currencies[domestic]
            f_idx = self.fx_rates_immediate.currencies[foreign]
            if path is None:
                path = self._get_recursive_chain(self.transform, f_idx, d_idx)[1]
            return d_idx, f_idx, path

        # perform a fast conversion if settlement aligns with known dates,
        if settlement is None:
            settlement = self.immediate
        elif settlement < self.immediate:
            raise ValueError("`settlement` cannot be before immediate FX rate date.")

        if settlement == self.fx_rates_immediate.settlement:
            rate_ = self.fx_rates_immediate.rate(pair)
            if return_path:
                _, _, path = _get_d_f_idx_and_path(pair, path)
                return rate_, path
            return rate_
        elif isinstance(self.fx_rates, FXRates) and \
                settlement == self.fx_rates.settlement:
            rate_ = self.fx_rates.rate(pair)
            if return_path:
                _, _, path = _get_d_f_idx_and_path(pair, path)
                return rate_, path
            return rate_

        # otherwise must rely on curves and path search which is slower
        d_idx, f_idx, path = _get_d_f_idx_and_path(pair, path)
        rate_, current_idx = 1.0, f_idx
        for route in path:
            if "col" in route:
                coll_ccy = self.currencies_list[current_idx]
                cash_ccy = self.currencies_list[route["col"]]
                w_i = self.fx_curves[f"{cash_ccy}{coll_ccy}"][settlement]
                v_i = self.fx_curves[f"{coll_ccy}{coll_ccy}"][settlement]
                rate_ *= self.fx_rates_immediate.fx_array[route["col"], current_idx]
                rate_ *= w_i / v_i
                current_idx = route["col"]
            elif "row" in route:
                coll_ccy = self.currencies_list[route["row"]]
                cash_ccy = self.currencies_list[current_idx]
                w_i = self.fx_curves[f"{cash_ccy}{coll_ccy}"][settlement]
                v_i = self.fx_curves[f"{coll_ccy}{coll_ccy}"][settlement]
                rate_ *= self.fx_rates_immediate.fx_array[route["row"], current_idx]
                rate_ *= v_i / w_i
                current_idx = route["row"]

        if return_path:
            return rate_, path
        return rate_

    def positions(
        self,
        value,
        base: Optional[str] = None,
        aggregate: bool = False
    ):
        """
        Convert a base value with FX rate sensitivities into an array of cash positions
        by settlement date.

        Parameters
        ----------
        value : float or Dual
            The amount expressed in base currency to convert to cash positions.
        base : str, optional
            The base currency in which ``value`` is given (3-digit code). If *None*
            assumes the ``base`` of the object.
        aggregate : bool, optional
            Whether to aggregate positions across all settlement dates and yield
            a single column Series.

        Returns
        -------
        DataFrame or Series

        Examples
        --------
        .. ipython:: python

           fxr1 = FXRates({"eurusd": 1.05}, settlement=dt(2022, 1, 3))
           fxr2 = FXRates({"usdcad": 1.1}, settlement=dt(2022, 1, 2))
           fxf = FXForwards(
               fx_rates=[fxr1, fxr2],
               fx_curves={
                   "usdusd": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "eureur": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "cadcad": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "usdeur": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "cadusd": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
               }
           )
           fxf.positions(
               value=Dual(100000, ["fx_eurusd", "fx_usdcad"], [-100000, -150000]),
               base="usd",
           )

        """
        if isinstance(value, (float, int)):
            value = Dual(value)
        base = self.base if base is None else base.lower()
        _ = np.array(
            [0 if ccy != base else float(value) for ccy in self.currencies_list]
        )  # this is an NPV so is assumed to be immediate settlement

        if isinstance(self.fx_rates, list):
            fx_rates = self.fx_rates
        else:
            fx_rates = [self.fx_rates]

        dates = list({fxr.settlement for fxr in fx_rates})
        if self.immediate not in dates:
            dates.insert(0, self.immediate)
        df = DataFrame(0., index=self.currencies_list, columns=dates)
        df.loc[base, self.immediate] = float(value)
        for pair in value.vars:
            if pair[:3] == "fx_":
                dom_, for_ = pair[3:6], pair[6:9]
                for fxr in fx_rates:
                    if dom_ in fxr.currencies_list and for_ in fxr.currencies_list:
                        delta = value.gradient(pair)[0]
                        _ = fxr._get_positions_from_delta(delta, pair[3:], base)
                        _ = Series(_, index=fxr.currencies_list, name=fxr.settlement)
                        df = df.add(_.to_frame(), fill_value=0.)

        if aggregate:
            return df.sum(axis=1)
        else:
            return df.sort_index(axis=1)

    def convert(
        self,
        value: Union[Dual, float],
        domestic: str,
        foreign: Optional[str] = None,
        settlement: Optional[datetime] = None,
        value_date: Optional[datetime] = None,
        collateral: Optional[str] = None,
        on_error: str = "ignore"
    ):
        """
        Convert an amount of a domestic currency, as of a settlement date
        into a foreign currency, valued on another date.

        Parameters
        ----------
        value : float or Dual
            The amount of the domestic currency to convert.
        domestic : str
            The domestic currency (3-digit code).
        foreign : str, optional
            The foreign currency to convert to (3-digit code). Uses instance
            ``base`` if not given.
        settlement : datetime, optional
            The date of the assumed domestic currency cashflow. If not given is
            assumed to be ``immediate`` settlement.
        value_date : datetime, optional
            The date for which the domestic cashflow is to be projected to. If not
            given is assumed to be equal to the ``settlement``.
        collateral : str, optional
            The collateral currency to project the cashflow if ``value_date`` is
            different to ``settlement``. If they are the same this is not needed.
            If not given defaults to ``domestic``.
        on_error : str in {"ignore", "warn", "raise"}
            The action taken if either ``domestic`` or ``foreign`` are not contained
            in the FX framework. `"ignore"` and `"warn"` will still return `None`.

        Returns
        -------
        Dual or None

        Examples
        --------

        .. ipython:: python

           fxr1 = FXRates({"eurusd": 1.05}, settlement=dt(2022, 1, 3))
           fxr2 = FXRates({"usdcad": 1.1}, settlement=dt(2022, 1, 2))
           fxf = FXForwards(
               fx_rates=[fxr1, fxr2],
               fx_curves={
                   "usdusd": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "eureur": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "cadcad": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "usdeur": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
                   "cadusd": Curve({dt(2022, 1, 1):1.0, dt(2022, 2, 1): 0.999}),
               }
           )
           fxf.convert(1000, "usd", "cad")

        """
        foreign = self.base if foreign is None else foreign.lower()
        domestic = domestic.lower()
        collateral = domestic if collateral is None else collateral.lower()
        for ccy in [domestic, foreign]:
            if ccy not in self.currencies:
                if on_error == "ignore":
                    return None
                elif on_error == "warn":
                    warnings.warn(
                        f"'{ccy}' not in FXForwards.currencies: returning None.",
                        UserWarning
                    )
                    return None
                else:
                    raise ValueError(f"'{ccy}' not in FXForwards.currencies.")

        if settlement is None:
            settlement = self.immediate
        if value_date is None:
            value_date = settlement

        fx_rate = self.rate(domestic + foreign, settlement)
        if value_date == settlement:
            return fx_rate * value
        else:
            crv = self.curve(foreign, collateral)
            return fx_rate * value * crv[settlement] / crv[value_date]

    def convert_positions(
        self,
        array: Union[np.array, list, DataFrame, Series],
        base: Optional[str] = None,
    ):
        """
        Convert an input of currency cash positions into a single base currency value.

        Parameters
        ----------
        array : list, 1d ndarray of floats, or Series, or DataFrame
            The cash positions to simultaneously convert to base currency value.
            If a DataFrame, must be indexed by currencies (3-digit lowercase) and the
            column headers must be settlement dates.
            If a Series, must be indexed by currencies (3-digit lowercase).
            If a 1d array or sequence, must
            be ordered by currency as defined in the attribute ``FXForward.currencies``.
        base : str, optional
            The currency to convert to (3-digit code). Uses instance ``base`` if not
            given.

        Returns
        -------
        Dual

        Examples
        --------

        .. ipython:: python

           fxr = FXRates({"usdnok": 8.0}, settlement=dt(2022, 1, 1))
           usdusd = Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.99})
           noknok = Curve({dt(2022, 1, 1): 1.0, dt(2023, 1, 1): 0.995})
           fxf = FXForwards(fxr, {"usdusd": usdusd, "noknok": noknok, "nokusd": noknok})
           fxf.currencies
           fxf.convert_positions([0, 1000000], "usd")

        .. ipython:: python

           fxr.convert_positions(Series([1000000, 0], index=["nok", "usd"]), "usd")

        .. ipython:: python

           positions = DataFrame(index=["usd", "nok"], data={
               dt(2022, 6, 2): [0, 1000000],
               dt(2022, 9, 7): [0, -1000000],
           })
           fxf.convert_positions(positions, "usd")
        """
        base = self.base if base is None else base.lower()

        if isinstance(array, Series):
            array_ = array.to_frame(name=self.immediate)
        elif isinstance(array, DataFrame):
            array_ = array
        else:
            array_ = DataFrame(
                {self.immediate: np.asarray(array)},
                index=self.currencies_list
            )

        # j = self.currencies[base]
        # return np.sum(array_ * self.fx_array[:, j])
        sum = 0
        for d in array_.columns:
            d_sum = 0
            for ccy in array_.index:
                d_sum += self.convert(array_.loc[ccy, d], ccy, base, d)
            if abs(d_sum) < 1e-2:
                sum += d_sum
            else:  # only discount if there is a real value
                sum += self.convert(d_sum, base, base, d, self.immediate)
        return sum

    def swap(
        self,
        pair: str,
        settlements: list[datetime],
        path: Optional[list[dict]] = None,
    ):
        """
        Return the FXSwap mid-market rate for the given currency pair.

        Parameters
        ----------
        pair : str
            The FX pair in usual domestic:foreign convention (6-digit code).
        settlements : list of datetimes,
            The settlement date of currency exchanges.
        path : list of dict, optional
            The chain of currency collateral curves to traverse to calculate the rate.
            This is calculated automatically and this argument is provided for
            internal calculation to avoid repeatedly calculating the same path. Use of
            this argument in normal circumstances is not recommended.

        Returns
        -------
        Dual
        """
        fx0 = self.rate(pair, settlements[0], path)
        fx1 = self.rate(pair, settlements[1], path)
        return (fx1 - fx0) * 10000

    def _full_curve(self, cashflow: str, collateral: str):
        """
        Calculate a cash collateral curve.

        Parameters
        ----------
        cashflow : str
            The currency in which cashflows are represented (3-digit code).
        collateral : str
            The currency of the CSA against which cashflows are collateralised (3-digit
            code).

        Returns
        -------
        Curve

        Notes
        -----
        Uses the formula,

        .. math::

           w_{DOM:FOR,i} = \\frac{f_{DOMFOR,i}}{F_{DOMFOR,0}} v_{FOR:FOR,i}

        The returned curve has each DF uniquely specified on each date.
        """
        cash_ccy, coll_ccy = cashflow.lower(), collateral.lower()
        cash_idx, coll_idx = self.currencies[cash_ccy], self.currencies[coll_ccy]
        path = self._get_recursive_chain(self.transform, coll_idx, cash_idx)[1]
        end = list(self.fx_curves[f"{coll_ccy}{coll_ccy}"].nodes.keys())[-1]
        days = (end - self.immediate).days
        nodes = {
            k: (
                self.rate(f"{cash_ccy}{coll_ccy}", k, path=path) /
                self.fx_rates_immediate.fx_array[cash_idx, coll_idx] *
                self.fx_curves[f"{coll_ccy}{coll_ccy}"][k]
            ) for k in [self.immediate + timedelta(days=i) for i in range(days+1)]
        }
        return Curve(nodes)

# Licence: Creative Commons - Attribution-NonCommercial-NoDerivatives 4.0 International
# Commercial use of this code, and/or copying and redistribution is prohibited.
# Contact rateslib at gmail.com if this code is observed outside its intended sphere.

    def curve(
        self,
        cashflow: str,
        collateral: str,
        convention: Optional[str] = None,
        modifier: Optional[Union[str, bool]] = False,
        calendar: Optional[Union[CustomBusinessDay, str, bool]] = False,
    ):
        """
        Return a cash collateral curve.

        Parameters
        ----------
        cashflow : str
            The currency in which cashflows are represented (3-digit code).
        collateral : str
            The currency of the CSA against which cashflows are collateralised (3-digit
            code).
        convention : str
            The day count convention used for calculating rates. If `None` defaults
            to the convention in the local cashflow currency.
        modifier : str, optional
            The modification rule, in {"F", "MF", "P", "MP"}, for determining rates.
            If `False` will default to the modifier in the local cashflow currency.
        calendar : calendar or str, optional
            The holiday calendar object to use. If str, lookups named calendar
            from static data. Used for determining rates. If `False` will
            default to the calendar in the local cashflow currency.

        Returns
        -------
        Curve or ProxyCurve

        Notes
        -----
        If the curve already exists within the attribute ``fx_curves`` that curve
        will be returned.

        Otherwise, returns a ``ProxyCurve`` which determines and rates
        and DFs via the chaining method and the below formula,

        .. math::

           w_{dom:for,i} = \\frac{f_{DOMFOR,i}}{F_{DOMFOR,0}} v_{for:for,i}

        The returned curve contains contrived methods to calculate rates and DFs
        from the combination of curves and FX rates that are available within
        the given :class:`FXForwards` instance.
        """
        cash_ccy, coll_ccy = cashflow.lower(), collateral.lower()
        pair = f"{cash_ccy}{coll_ccy}"
        if pair in self.fx_curves:
            return self.fx_curves[pair]

        return ProxyCurve(
            cashflow=cash_ccy,
            collateral=coll_ccy,
            fx_forwards=self,
            convention=convention,
            modifier=modifier,
            calendar=calendar,
        )

    def plot(
        self,
        pair: str,
        right: Optional[Union[datetime, str]] = None,
        left: Optional[Union[datetime, str]] = None,
        fx_swap: bool = False,
    ):
        """
        Plot given forward FX rates.

        Parameters
        ----------
        pair : str
            The FX pair to determine rates for (6-digit code).
        right : datetime or str, optional
            The right bound of the graph. If given as str should be a tenor format
            defining a point measured from the initial node date of the curve.
            Defaults to the terminal date of the FXForwards object.
        left : datetime or str, optional
            The left bound of the graph. If given as str should be a tenor format
            defining a point measured from the initial node date of the curve.
            Defaults to the immediate FX settlement date.
        fx_swap : bool
            Whether to plot as the FX rate or as FX swap points relative to the
            initial FX rate on the left side of the chart.
            Default is `False`.

        Returns
        -------
        (fig, ax, line) : Matplotlib.Figure, Matplotplib.Axes, Matplotlib.Lines2D
        """
        if left is None:
            left_: datetime = self.immediate
        elif isinstance(left, str):
            left_ = add_tenor(self.immediate, left, None, None)
        elif isinstance(left, datetime):
            left_ = left
        else:
            raise ValueError("`left` must be supplied as datetime or tenor string.")

        if right is None:
            right_: datetime = self.terminal
        elif isinstance(right, str):
            right_ = add_tenor(self.immediate, right, None, None)
        elif isinstance(right, datetime):
            right_ = right
        else:
            raise ValueError("`right` must be supplied as datetime or tenor string.")

        points : int = (right_ - left_).days
        x = [left_ + timedelta(days=i) for i in range(points)]
        _, path = self.rate(pair, x[0], return_path=True)
        rates = [self.rate(pair, _, path=path) for _ in x]
        if not fx_swap:
            y = [rates]
        else:
            y = [(rate - rates[0])*10000 for rate in rates]
        return plot(x, y)

    def _set_ad_order(self, order):
        self._ad = order
        for curve in self.fx_curves.values():
            curve._set_ad_order(order)

        if isinstance(self.fx_rates, list):
            for fx_rates in self.fx_rates:
                fx_rates._set_ad_order(order)
        else:
            self.fx_rates._set_ad_order(order)
        self.fx_rates_immediate._set_ad_order(order)

    def to_json(self):
        if isinstance(self.fx_rates, list):
            fx_rates = [_.to_json() for _ in self.fx_rates]
        else:
            fx_rates = self.fx_rates.to_json()
        container = {
            "base": self.base,
            "fx_rates": fx_rates,
            "fx_curves": {k: v.to_json() for k, v in self.fx_curves.items()}
        }
        return json.dumps(container, default=str)

    @classmethod
    def from_json(cls, fx_forwards, **kwargs):
        """
        Loads an FXForwards object from JSON.

        Parameters
        ----------
        fx_forwards : str
            JSON string describing the FXForwards class. Typically constructed with
            :meth:`to_json`.

        Returns
        -------
        FXForwards

        Notes
        -----
        This method also creates new ``FXRates`` and ``Curve`` objects from JSON.
        These new objects can be accessed from the attributes of the ``FXForwards``
        instance.
        """
        serial = json.loads(fx_forwards)

        if isinstance(serial["fx_rates"], list):
            fx_rates = [FXRates.from_json(_) for _ in serial["fx_rates"]]
        else:
            fx_rates = FXRates.from_json(serial["fx_rates"])

        fx_curves = {k: Curve.from_json(v) for k, v in serial["fx_curves"].items()}
        base = serial["base"]
        return FXForwards(fx_rates, fx_curves, base)

    def __eq__(self, other):
        """Test two FXForwards are identical"""
        if type(self) != type(other):
            return False
        for attr in ["base"]:
            if getattr(self, attr, None) != getattr(other, attr, None):
                return False
        if self.fx_rates_immediate != other.fx_rates_immediate:
            return False

        # it is sufficient to check that FX immediate and curves are equivalent.

        # if type(self.fx_rates) != type(other.fx_rates):
        #     return False
        # if isinstance(self.fx_rates, list):
        #     if len(self.fx_rates) != len(other.fx_rates):
        #         return False
        #     for i in range(len(self.fx_rates)):
        #         # this tests FXRates are also ordered in the same on each object
        #         if self.fx_rates[i] != other.fx_rates[i]:
        #             return False
        # else:
        #     if self.fx_rates != other.fx_rates:
        #         return False

        for k, curve in self.fx_curves.items():
            if k not in other.fx_curves:
                return False
            if curve != other.fx_curves[k]:
                return False

        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def copy(self):
        """
        An FXForwards copy creates a new object with copied references.
        """
        return self.from_json(self.to_json())


class ProxyCurve(Curve):
    """
    Create a curve which is defined by other curves and related via
    :class:`~rateslib.fx.FXForwards`.

    Parameters
    ----------
    cashflow : str
        The currency in which cashflows are represented (3-digit code).
    collateral : str
        The currency of the CSA against which cashflows are collateralised (3-digit
        code).
    fx_forwards : FXForwards
        The :class:`~rateslib.fx.FXForwards` object which contains the relating
        FX information and the available :class:`~rateslib.curves.Curve` s.
    convention : str
        The day count convention used for calculating rates. If `None` defaults
        to the convention in the local cashflow currency.
    modifier : str, optional
        The modification rule, in {"F", "MF", "P", "MP"}, for determining rates.
        If `False` will default to the modifier in the local cashflow currency.
    calendar : calendar or str, optional
        The holiday calendar object to use. If str, lookups named calendar
        from static data. Used for determining rates. If `False` will
        default to the calendar in the local cashflow currency.

    Notes
    -----
    The DFs returned are calculated via the chaining method and the below formula,
    relating the DF curve in the local collateral currency and FX forward rates.

    .. math::

       w_{dom:for,i} = \\frac{f_{DOMFOR,i}}{F_{DOMFOR,0}} v_{for:for,i}

    The returned curve contains contrived methods to calculate this dynamically and
    efficiently from the combination of curves and FX rates that are available within
    the given :class:`FXForwards` instance.
    """
    def __init__(
        self,
        cashflow: str,
        collateral: str,
        fx_forwards: FXForwards,
        convention: Optional[str] = None,
        modifier: Optional[Union[str, bool]] = False,
        calendar: Optional[Union[CustomBusinessDay, bool]] = False,
    ):
        cash_ccy, coll_ccy = cashflow.lower(), collateral.lower()
        self._is_proxy = True
        self.fx_forwards = fx_forwards
        self.cash_currency = cash_ccy
        self.cash_pair = f"{cash_ccy}{cash_ccy}"
        self.cash_idx = self.fx_forwards.currencies[cash_ccy]
        self.coll_currency = coll_ccy
        self.coll_pair = f"{coll_ccy}{coll_ccy}"
        self.coll_idx = self.fx_forwards.currencies[coll_ccy]
        self.pair = f"{cash_ccy}{coll_ccy}"
        self.path = self.fx_forwards._get_recursive_chain(
            self.fx_forwards.transform, self.coll_idx, self.cash_idx
        )[1]
        self.terminal = list(
            self.fx_forwards.fx_curves[self.cash_pair].nodes.keys()
        )[-1]

        default_curve = Curve(
            {},
            convention=self.fx_forwards.fx_curves[self.cash_pair].convention if convention is None else convention,
            modifier=self.fx_forwards.fx_curves[self.cash_pair].modifier if modifier is False else modifier,
            calendar=self.fx_forwards.fx_curves[self.cash_pair].calendar if calendar is False else calendar,
        )
        self.convention = default_curve.convention
        self.modifier = default_curve.modifier
        self.calendar = default_curve.calendar
        self.node_dates = [self.fx_forwards.immediate, self.terminal]

    def __getitem__(self, date: datetime):
        return (
            self.fx_forwards.rate(self.pair, date, path=self.path) /
            self.fx_forwards.fx_rates_immediate.fx_array[self.cash_idx, self.coll_idx] *
            self.fx_forwards.fx_curves[self.coll_pair][date]
        )

    def to_json(self):  # pragma: no cover
        """
        Not implemented for :class:`~rateslib.fx.ProxyCurve` s.
        :return:
        """
        return NotImplementedError("`to_json` not available on proxy curve.")

    def from_json(self):  # pragma: no cover
        """
        Not implemented for :class:`~rateslib.fx.ProxyCurve` s.
        """
        return NotImplementedError("`from_json` not available on proxy curve.")

    def _set_ad_order(self):  # pragma: no cover
        """
        Not implemented for :class:`~rateslib.fx.ProxyCurve` s.
        """
        return NotImplementedError("`set_ad_order` not available on proxy curve.")

# Licence: Creative Commons - Attribution-NonCommercial-NoDerivatives 4.0 International
# Commercial use of this code, and/or copying and redistribution is prohibited.
# Contact rateslib at gmail.com if this code is observed outside its intended sphere.

#####

# TODO:

# 1) PERFORMANCE:
# Profiling shows that dual_solve for the determination of fx_vector is quite slow
# due to the structure and sparsity of the matrix it should be possible to use a
# more direct algorithm to determine the dual gradients of the fx vector components.

# 2) UTILITY:
# Consider allowing a to_json method for proxy curves to mediate exchange of info.
# Or better yet just configure a to_json method for an FXForwards object.
