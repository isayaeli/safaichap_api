from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalogue import seed_data
from apps.catalogue.models import (
    Destination, Itinerary, ItineraryDay, ItineraryPricing, Operator, RefundPolicy, SeasonalAdjustment,
)
from apps.core.models import AppSetting, FxRate


class Command(BaseCommand):
    help = "Seeds the catalogue from the app's mock_seed.dart (idempotent: updates by name/slug)."

    def add_arguments(self, parser):
        parser.add_argument('--no-fx', action='store_true', help="Don't add the default FX rates.")

    @transaction.atomic
    def handle(self, *args, **options):
        AppSetting.get()
        policy, _ = RefundPolicy.objects.get_or_create(name='Standard', defaults={'is_default': True})

        operators = {}
        for key, data in seed_data.OPERATORS.items():
            operators[key], _ = Operator.objects.update_or_create(
                name=data['name'],
                defaults={
                    'lead_time_days': data['lead_time_days'], 'phone_number': seed_data.OPERATOR_PHONE,
                    'whatsapp': seed_data.OPERATOR_PHONE, 'email': data['email'], 'refund_policy': policy,
                },
            )

        destinations = {}
        for data in seed_data.DESTINATIONS:
            destinations[data['name']], _ = Destination.objects.update_or_create(
                name=data['name'], defaults={'region': data['region'], 'image': data['image']},
            )

        count = len(seed_data.ITINERARIES)
        for index, data in enumerate(seed_data.ITINERARIES):
            itinerary, _ = Itinerary.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'title': data['title'], 'summary': data['summary'], 'duration_days': data['duration_days'],
                    'accommodation_level': data['accommodation_level'], 'inclusions': data['inclusions'],
                    'exclusions': data['exclusions'], 'images': data['images'],
                    'operator': operators[data['operator']], 'lead_time_days': data['lead_time_days'],
                    'min_group_size': data['min_group_size'], 'max_group_size': data['max_group_size'],
                    'is_active': True, 'is_featured': index < 4, 'sort_order': index,
                },
            )
            itinerary.set_destinations([destinations[name] for name in data['destinations']])

            itinerary.days.all().delete()
            ItineraryDay.objects.bulk_create([ItineraryDay(itinerary=itinerary, **day) for day in data['days']])

            p = data['pricing']
            pricing, _ = ItineraryPricing.objects.update_or_create(
                itinerary=itinerary,
                defaults={k: p[k] for k in ('base_currency', 'resident_adult', 'resident_child',
                                            'non_resident_adult', 'non_resident_child')},
            )
            pricing.seasonal_adjustments.all().delete()
            if p['seasons'] == 'high':
                SeasonalAdjustment.objects.bulk_create([
                    SeasonalAdjustment(pricing=pricing, **season) for season in seed_data.high_seasons()
                ])

        if not options['no_fx'] and not FxRate.objects.exists():
            now = timezone.now()
            FxRate.objects.bulk_create([
                FxRate(from_currency=code, to_currency='TZS', numerator=rate, denominator=1,
                       source='seed', fetched_at=now)
                for code, rate in seed_data.FX_TZS_PER_UNIT.items()
            ])

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(operators)} operators, {len(destinations)} destinations, {count} itineraries."
        ))
