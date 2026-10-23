"""
Money helpers. Amounts are always integers in minor units of a currency:
TZS has no minor unit (1 per major), USD/EUR/GBP have 100.
"""

MINOR_PER_MAJOR = {
    'TZS': 1,
    'USD': 100,
    'EUR': 100,
    'GBP': 100,
}

CURRENCY_CHOICES = [(code, code) for code in MINOR_PER_MAJOR]

MOBILE_MONEY_CURRENCY = 'TZS'


def is_supported(currency: str) -> bool:
    return currency in MINOR_PER_MAJOR


def minor_per_major(currency: str) -> int:
    try:
        return MINOR_PER_MAJOR[currency]
    except KeyError:
        raise ValueError(f"Unsupported currency: {currency}")


def ceil_div(a: int, b: int) -> int:
    """Integer division rounding up (for non-negative a, positive b)."""
    return -(-a // b)


def convert(amount_minor: int, from_currency: str, to_currency: str, numerator: int, denominator: int) -> int:
    """
    Converts minor units of `from_currency` into minor units of `to_currency`
    with a rational rate (1 major `from` = numerator/denominator major `to`),
    rounding UP to the nearest minor unit. Mirrors the app's FxRate.convert.
    """
    if denominator <= 0:
        raise ValueError("FX denominator must be positive")
    if from_currency == to_currency:
        return amount_minor
    num = amount_minor * numerator * minor_per_major(to_currency)
    den = denominator * minor_per_major(from_currency)
    return ceil_div(num, den)


def multiply_bps(amount_minor: int, bps: int) -> int:
    """amount × bps / 10000, rounded up (season multipliers)."""
    return ceil_div(amount_minor * bps, 10000)


def format_major(amount_minor: int, currency: str) -> str:
    """'TZS 5,000' / 'USD 12.50' for user-facing messages."""
    factor = minor_per_major(currency)
    if factor == 1:
        return f"{currency} {amount_minor:,}"
    major, minor = divmod(amount_minor, factor)
    if minor == 0:
        return f"{currency} {major:,}"
    return f"{currency} {major:,}.{minor:02d}"
