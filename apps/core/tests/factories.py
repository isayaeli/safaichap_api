from datetime import timedelta

from django.utils import timezone

from apps.catalogue.models import (
    Destination, Itinerary, ItineraryPricing, Operator, SeasonalAdjustment,
)
from apps.core.models import FxRate
from apps.userauth.models import UserAccount


def make_user(username='uid-1', **kwargs):
    defaults = {'full_name': 'Asha Mushi', 'residency': 'resident', 'preferred_currency': 'TZS',
                'phone_number': '+255712345678'}
    defaults.update(kwargs)
    return UserAccount.objects.create(username=username, **defaults)


def make_fx():
    now = timezone.now()
    for code, rate in (('USD', 2600), ('EUR', 2800), ('GBP', 3300)):
        FxRate.objects.create(from_currency=code, to_currency='TZS', numerator=rate, denominator=1, fetched_at=now)


def make_itinerary(base_currency='TZS', prices=(480000, 260000, 1250000, 700000), lead=14, **kwargs):
    operator = Operator.objects.create(name='Kili Trails Safaris', lead_time_days=lead,
                                       phone_number='+255754000111', email='bookings@kilitrails.co.tz')
    defaults = dict(title='Tarangire Weekend', slug=f"trip-{Itinerary.objects.count() + 1}", duration_days=2,
                    accommodation_level='budget', operator=operator, min_group_size=1, max_group_size=6,
                    images=['https://img/cover.jpg'])
    defaults.update(kwargs)
    itinerary = Itinerary.objects.create(**defaults)
    dest, _ = Destination.objects.get_or_create(name='Tarangire', defaults={'region': 'Northern circuit'})
    itinerary.set_destinations([dest])
    pricing = ItineraryPricing.objects.create(
        itinerary=itinerary, base_currency=base_currency, resident_adult=prices[0], resident_child=prices[1],
        non_resident_adult=prices[2], non_resident_child=prices[3],
    )
    return itinerary, pricing


def add_season(pricing, start, end, bps=12000, label='High season (+20%)'):
    return SeasonalAdjustment.objects.create(pricing=pricing, start_date=start, end_date=end,
                                             multiplier_bps=bps, label=label)


def days_from_today(n):
    return timezone.localdate() + timedelta(days=n)
