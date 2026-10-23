import logging
from fractions import Fraction

import requests
from celery import shared_task
from decouple import config
from django.utils import timezone

from apps.core.models import FxRate

logger = logging.getLogger(__name__)

FX_PROVIDER_URL = config('FX_PROVIDER_URL', default='https://open.er-api.com/v6/latest/TZS')
FX_CURRENCIES = ('USD', 'EUR', 'GBP')


@shared_task
def refresh_fx_rates():
    """
    Daily: stores TZS-per-unit rates for USD/EUR/GBP as exact fractions
    (numerator/denominator), from a provider quoting 1 TZS in each currency.
    """
    try:
        response = requests.get(FX_PROVIDER_URL, timeout=20)
        response.raise_for_status()
        rates = response.json().get('rates') or {}
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error("FX refresh failed: %s", type(e).__name__)
        return {"status": "error"}

    now = timezone.now()
    stored = {}
    for code in FX_CURRENCIES:
        per_tzs = rates.get(code)
        if not per_tzs:
            continue
        # 1 TZS = per_tzs units → 1 unit = 1/per_tzs TZS, kept to 4 decimals.
        tzs_per = Fraction(1 / float(per_tzs)).limit_denominator(10000)
        FxRate.objects.create(
            from_currency=code, to_currency='TZS',
            numerator=tzs_per.numerator, denominator=tzs_per.denominator,
            source=FX_PROVIDER_URL, fetched_at=now,
        )
        stored[code] = f"{tzs_per.numerator}/{tzs_per.denominator}"
    logger.info("FX rates refreshed: %s", stored)
    return stored
