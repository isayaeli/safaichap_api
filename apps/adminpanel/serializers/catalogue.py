from django.db import transaction
from rest_framework import serializers

from apps.catalogue.models import (
    Destination, Itinerary, ItineraryDay, ItineraryPricing, Operator, RefundPolicy, SeasonalAdjustment,
)


class RefundPolicySerializer(serializers.ModelSerializer):
    operators_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminRefundPolicy'
        model = RefundPolicy
        fields = ['uuid', 'name', 'tiers', 'processing_fee_bps', 'description', 'is_default', 'operators_count',
                  'created_at']
        read_only_fields = ['uuid', 'created_at']

    def validate_tiers(self, tiers):
        if not isinstance(tiers, list) or not tiers:
            raise serializers.ValidationError("Add at least one tier.")
        seen = set()
        for tier in tiers:
            try:
                days, pct = int(tier['min_days']), int(tier['percentage'])
            except (KeyError, TypeError, ValueError):
                raise serializers.ValidationError("Each tier needs whole-number `min_days` and `percentage`.")
            if days < 0 or not 0 <= pct <= 100:
                raise serializers.ValidationError("Days can't be negative and percentages must be 0–100.")
            if days in seen:
                raise serializers.ValidationError("Two tiers have the same number of days.")
            seen.add(days)
        if 0 not in seen:
            raise serializers.ValidationError("Add a tier for 0 days so every cancellation is covered.")
        return sorted(({'min_days': int(t['min_days']), 'percentage': int(t['percentage'])} for t in tiers),
                      key=lambda t: t['min_days'], reverse=True)

    def validate_processing_fee_bps(self, value):
        if value > 10000:
            raise serializers.ValidationError("The fee can't exceed 100%.")
        return value

    def save(self, **kwargs):
        with transaction.atomic():
            policy = super().save(**kwargs)
            if policy.is_default:
                RefundPolicy.objects.exclude(pk=policy.pk).update(is_default=False)
        return policy


class OperatorSerializer(serializers.ModelSerializer):
    refund_policy = serializers.SlugRelatedField(slug_field='uuid', queryset=RefundPolicy.objects.all(),
                                                 allow_null=True, required=False)
    refund_policy_name = serializers.CharField(source='refund_policy.name', read_only=True, default=None)
    itineraries_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminOperator'
        model = Operator
        fields = ['uuid', 'name', 'lead_time_days', 'phone_number', 'whatsapp', 'email', 'refund_policy',
                  'refund_policy_name', 'itineraries_count', 'created_at']
        read_only_fields = ['uuid', 'created_at']


class DestinationSerializer(serializers.ModelSerializer):
    itineraries_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminDestination'
        model = Destination
        fields = ['uuid', 'name', 'region', 'image', 'itineraries_count', 'created_at']
        read_only_fields = ['uuid', 'created_at']


class DaySerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminDay'
        model = ItineraryDay
        fields = ['day_number', 'title', 'description', 'location', 'meals', 'accommodation']


class SeasonSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminSeason'
        model = SeasonalAdjustment
        fields = ['start_date', 'end_date', 'multiplier_bps', 'label']

    def validate(self, data):
        if data['end_date'] < data['start_date']:
            raise serializers.ValidationError("The season ends before it starts.")
        if not 1000 <= data['multiplier_bps'] <= 50000:
            raise serializers.ValidationError("The multiplier must be between 0.1× and 5×.")
        return data


class PricingSerializer(serializers.ModelSerializer):
    seasonal_adjustments = SeasonSerializer(many=True, required=False)

    class Meta:
        ref_name = 'AdminPricing'
        model = ItineraryPricing
        fields = ['base_currency', 'resident_adult', 'resident_child', 'non_resident_adult', 'non_resident_child',
                  'seasonal_adjustments']

    def validate(self, data):
        for name in ('resident_adult', 'resident_child', 'non_resident_adult', 'non_resident_child'):
            if data.get(name, 0) < 0:
                raise serializers.ValidationError({name: ["Prices can't be negative."]})
        return data


class ItineraryListSerializer(serializers.ModelSerializer):
    operator_uuid = serializers.UUIDField(source='operator.uuid', read_only=True)
    operator_name = serializers.CharField(source='operator.name', read_only=True)
    destinations = serializers.SerializerMethodField()
    base_currency = serializers.CharField(source='pricing.base_currency', read_only=True, default=None)
    from_price = serializers.IntegerField(source='pricing.resident_adult', read_only=True, default=None)
    goals_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminItineraryList'
        model = Itinerary
        fields = ['uuid', 'title', 'slug', 'duration_days', 'accommodation_level', 'operator_uuid', 'operator_name',
                  'destinations', 'images', 'is_active', 'is_featured', 'sort_order', 'base_currency', 'from_price',
                  'goals_count', 'created_at', 'updated_at']

    def get_destinations(self, obj):
        return obj.ordered_destination_names()


class ItinerarySerializer(serializers.ModelSerializer):
    """Writable trip with nested days, ordered destinations and pricing (lists are replaced as a whole)."""
    operator = serializers.SlugRelatedField(slug_field='uuid', queryset=Operator.objects.all())
    destinations = serializers.SlugRelatedField(slug_field='uuid', queryset=Destination.objects.all(), many=True,
                                                required=False)
    days = DaySerializer(many=True, required=False)
    pricing = PricingSerializer()
    goals_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminItinerary'
        model = Itinerary
        fields = ['uuid', 'title', 'slug', 'summary', 'duration_days', 'accommodation_level', 'inclusions',
                  'exclusions', 'images', 'operator', 'lead_time_days', 'min_group_size', 'max_group_size',
                  'is_active', 'is_featured', 'sort_order', 'kyc_required', 'destinations', 'days', 'pricing',
                  'goals_count', 'created_at', 'updated_at']
        read_only_fields = ['uuid', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['destinations'] = [str(link.destination.uuid) for link in instance.destination_links.all()]
        return data

    def validate(self, data):
        lo = data.get('min_group_size', getattr(self.instance, 'min_group_size', 1))
        hi = data.get('max_group_size', getattr(self.instance, 'max_group_size', 10))
        if lo < 1 or hi < lo:
            raise serializers.ValidationError({'max_group_size': ["Must be at least the minimum group size."]})
        days = data.get('days')
        if days is not None:
            numbers = [d['day_number'] for d in days]
            if len(numbers) != len(set(numbers)):
                raise serializers.ValidationError({'days': ["Day numbers must be unique."]})
        for key in ('inclusions', 'exclusions', 'images'):
            if key in data and not isinstance(data[key], list):
                raise serializers.ValidationError({key: ["Must be a list."]})
        return data

    def _write_nested(self, itinerary, destinations, days, pricing):
        if destinations is not None:
            itinerary.set_destinations(destinations)
        if days is not None:
            itinerary.days.all().delete()
            ItineraryDay.objects.bulk_create([ItineraryDay(itinerary=itinerary, **d) for d in days])
        if pricing is not None:
            seasons = pricing.pop('seasonal_adjustments', None)
            obj, _ = ItineraryPricing.objects.update_or_create(itinerary=itinerary, defaults=pricing)
            itinerary.pricing = obj
            if seasons is not None:
                obj.seasonal_adjustments.all().delete()
                SeasonalAdjustment.objects.bulk_create([SeasonalAdjustment(pricing=obj, **s) for s in seasons])

    @transaction.atomic
    def create(self, validated_data):
        destinations = validated_data.pop('destinations', [])
        days = validated_data.pop('days', [])
        pricing = validated_data.pop('pricing')
        itinerary = Itinerary.objects.create(**validated_data)
        self._write_nested(itinerary, destinations, days, pricing)
        return itinerary

    @transaction.atomic
    def update(self, instance, validated_data):
        destinations = validated_data.pop('destinations', None)
        days = validated_data.pop('days', None)
        pricing = validated_data.pop('pricing', None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        self._write_nested(instance, destinations, days, pricing)
        return instance
