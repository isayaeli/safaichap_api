"""
Total cost rules, ported from the app's lib/src/core/utils/pricing_calculator.dart.

Works on a pricing dict shaped like the API `pricing` object (see
ItineraryPricing.to_dict), so the same code prices live itineraries and
locked snapshots.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date

from apps.catalogue.models import AGE_ORDER, RESIDENCY_ORDER
from utils.money import convert, multiply_bps

DEFAULT_BPS = 10000


@dataclass
class PriceLine:
    residency: str
    age_category: str
    count: int
    unit_price: int  # per person, goal currency, season-adjusted

    @property
    def subtotal(self) -> int:
        return self.unit_price * self.count

    def to_dict(self) -> dict:
        return {
            'residency': str(self.residency),
            'age_category': str(self.age_category),
            'count': self.count,
            'unit_price': self.unit_price,
            'subtotal': self.subtotal,
        }


@dataclass
class PriceBreakdown:
    currency: str
    lines: list[PriceLine]
    total: int
    season_label: str | None
    multiplier_bps: int


def adjustment_for(pricing: dict, travel_date: date) -> dict | None:
    """First seasonal adjustment (by start_date) whose inclusive range covers the date."""
    adjustments = sorted(pricing.get('seasonal_adjustments') or [], key=lambda a: a['start_date'])
    for a in adjustments:
        if date.fromisoformat(a['start_date']) <= travel_date <= date.fromisoformat(a['end_date']):
            return a
    return None


def price_for(pricing: dict, residency: str, age_category: str) -> int:
    return pricing[f"{residency}_{age_category}"]


def quote(pricing: dict, travellers: list[dict], travel_date: date, currency: str,
          fx_numerator: int, fx_denominator: int) -> PriceBreakdown:
    """
    Season is applied per person in the base currency BEFORE conversion, so
    unit_price × count equals the subtotal exactly.
    """
    base_currency = pricing['base_currency']
    adjustment = adjustment_for(pricing, travel_date)
    bps = adjustment['multiplier_bps'] if adjustment else DEFAULT_BPS

    counts = Counter((t['residency'], t['age_category']) for t in travellers)
    lines = []
    for residency in RESIDENCY_ORDER:
        for age in AGE_ORDER:
            count = counts.get((residency.value, age.value), 0)
            if not count:
                continue
            seasonal = multiply_bps(price_for(pricing, residency.value, age.value), bps)
            unit = convert(seasonal, base_currency, currency, fx_numerator, fx_denominator)
            lines.append(PriceLine(residency.value, age.value, count, unit))

    return PriceBreakdown(
        currency=currency,
        lines=lines,
        total=sum(line.subtotal for line in lines),
        season_label=adjustment['label'] if adjustment else None,
        multiplier_bps=bps,
    )
