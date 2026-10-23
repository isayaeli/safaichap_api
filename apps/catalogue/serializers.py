from rest_framework import serializers

from apps.core.choices import AgeCategory
from apps.core.fx import get_rate
from apps.core.models import AppSetting
from utils.money import convert
from .models import Destination, Itinerary, ItineraryDay, ItineraryPricing, SeasonalAdjustment


def display_price(itinerary: Itinerary, residency: str, currency: str, rates: dict | None = None) -> int:
    """Per-adult price for `residency`, converted to `currency` at today's rate. No season multiplier."""
    pricing = itinerary.pricing
    base = pricing.price_for(residency, AgeCategory.ADULT)
    if rates is None:
        rates = {}
    key = (pricing.base_currency, currency)
    if key not in rates:
        rates[key] = get_rate(*key)
    num, den = rates[key]
    return convert(base, pricing.base_currency, currency, num, den)


class DestinationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Destination
        fields = ['name', 'region', 'image']


class ItineraryDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = ItineraryDay
        fields = ['day_number', 'title', 'description', 'location', 'meals', 'accommodation']


class SeasonalAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeasonalAdjustment
        fields = ['start_date', 'end_date', 'multiplier_bps', 'label']


class ItineraryPricingSerializer(serializers.ModelSerializer):
    seasonal_adjustments = SeasonalAdjustmentSerializer(many=True, read_only=True)

    class Meta:
        model = ItineraryPricing
        fields = ['base_currency', 'resident_adult', 'resident_child', 'non_resident_adult',
                  'non_resident_child', 'seasonal_adjustments']


class ItinerarySerializer(serializers.ModelSerializer):
    """
    Context: `residency`, `currency` (for display_price) and an optional shared
    `rates` dict so a page of itineraries hits the FX table once per currency pair.
    """
    destinations = serializers.SerializerMethodField()
    days = ItineraryDaySerializer(many=True, read_only=True)
    pricing = ItineraryPricingSerializer(read_only=True)
    operator_uuid = serializers.UUIDField(source='operator.uuid', read_only=True)
    operator_name = serializers.CharField(source='operator.name', read_only=True)
    operator_lead_time_days = serializers.SerializerMethodField()
    display_price = serializers.SerializerMethodField()
    display_currency = serializers.SerializerMethodField()

    class Meta:
        model = Itinerary
        fields = [
            'uuid', 'title', 'slug', 'summary', 'destinations', 'duration_days', 'accommodation_level',
            'days', 'inclusions', 'exclusions', 'images', 'operator_uuid', 'operator_name',
            'operator_lead_time_days', 'min_group_size', 'max_group_size', 'is_active', 'pricing',
            'display_price', 'display_currency',
        ]

    def _default_lead(self):
        if 'default_lead_time_days' not in self.context:
            self.context['default_lead_time_days'] = AppSetting.get().default_lead_time_days
        return self.context['default_lead_time_days']

    def get_operator_lead_time_days(self, obj):
        return obj.effective_lead_time_days(self._default_lead())

    def get_destinations(self, obj):
        return obj.ordered_destination_names()

    def get_display_price(self, obj):
        if getattr(obj, '_display_price', None) is not None:
            return obj._display_price
        return display_price(obj, self.context['residency'], self.context['currency'], self.context.setdefault('rates', {}))

    def get_display_currency(self, obj):
        return self.context['currency']
