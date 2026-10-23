from apps.core.models import FxRate

# Used until the first refresh_fx_rates run (same as the app's mock backend).
FALLBACK_TZS_PER_UNIT = {
    'TZS': (1, 1),
    'USD': (2600, 1),
    'EUR': (2800, 1),
    'GBP': (3300, 1),
}


def tzs_per_unit(currency: str) -> tuple[int, int]:
    """TZS per one major unit of `currency`, as (numerator, denominator)."""
    if currency == 'TZS':
        return (1, 1)
    rate = (
        FxRate.objects.filter(from_currency=currency, to_currency='TZS')
        .order_by('-fetched_at').first()
    )
    if rate:
        return (rate.numerator, rate.denominator)
    return FALLBACK_TZS_PER_UNIT[currency]


def get_rate(from_currency: str, to_currency: str) -> tuple[int, int]:
    """
    Today's rate as (numerator, denominator): 1 major `from` = num/den major `to`.
    Cross rates: from→to = tzs_per[from] / tzs_per[to].
    """
    if from_currency == to_currency:
        return (1, 1)
    f_num, f_den = tzs_per_unit(from_currency)
    t_num, t_den = tzs_per_unit(to_currency)
    return (f_num * t_den, f_den * t_num)
