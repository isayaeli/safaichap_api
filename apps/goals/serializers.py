from rest_framework import serializers

from apps.core.choices import AgeCategory, GoalStatus, PaymentFrequency, Residency
from utils.money import CURRENCY_CHOICES
from .models import Installment, SavingsGoal, Traveller
from .services.goals import next_open_installment


class TravellerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=150, trim_whitespace=True)
    age_category = serializers.ChoiceField(choices=AgeCategory.choices)
    residency = serializers.ChoiceField(choices=Residency.choices)

    class Meta:
        model = Traveller
        fields = ['name', 'age_category', 'residency']


class InstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Installment
        fields = ['uuid', 'due_date', 'amount', 'amount_paid', 'status', 'is_deposit']


class SavingsGoalSerializer(serializers.ModelSerializer):
    itinerary_uuid = serializers.UUIDField(source='itinerary.uuid', read_only=True)
    travellers = TravellerSerializer(many=True, read_only=True)
    installments = serializers.SerializerMethodField()
    installment_amount = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    booking_uuid = serializers.SerializerMethodField()

    class Meta:
        model = SavingsGoal
        fields = [
            'uuid', 'itinerary_uuid', 'title', 'travellers', 'travel_date', 'pay_by_date', 'currency',
            'total_amount', 'deposit_amount', 'amount_paid', 'frequency', 'installment_amount', 'next_due_date',
            'status', 'consecutive_missed', 'cover_image', 'booking_uuid', 'created_at', 'completed_at',
            'installments',
        ]

    def _installments(self, obj):
        if not hasattr(obj, '_installments_cache'):
            obj._installments_cache = sorted(obj.installments.all(), key=lambda i: (i.due_date, i.position))
        return obj._installments_cache

    def _next_open(self, obj):
        if obj.status == GoalStatus.COMPLETED:
            return None
        return next_open_installment(self._installments(obj))

    def get_installments(self, obj):
        return InstallmentSerializer(self._installments(obj), many=True).data

    def get_installment_amount(self, obj):
        nxt = self._next_open(obj)
        return nxt.amount - nxt.amount_paid if nxt else 0

    def get_next_due_date(self, obj):
        nxt = self._next_open(obj)
        return nxt.due_date.isoformat() if nxt else None

    def get_cover_image(self, obj):
        return obj.itinerary.cover_image

    def get_booking_uuid(self, obj):
        booking = getattr(obj, 'booking', None)
        return str(booking.uuid) if booking else None


class PlanSerializer(serializers.Serializer):
    """Body for POST /api/goals/quote/ and POST /api/goals/."""
    itinerary_uuid = serializers.UUIDField()
    travellers = TravellerSerializer(many=True)
    travel_date = serializers.DateField()
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES)
    frequency = serializers.ChoiceField(choices=PaymentFrequency.choices, default=PaymentFrequency.MONTHLY)
    deposit_amount = serializers.IntegerField(min_value=0, default=0)
    custom_days = serializers.IntegerField(min_value=1, max_value=365, default=30, allow_null=True)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, allow_null=True)

    def validate_custom_days(self, value):
        return value or 30


class RescheduleSerializer(serializers.Serializer):
    travel_date = serializers.DateField()
    frequency = serializers.ChoiceField(choices=PaymentFrequency.choices, required=False, allow_null=True)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1000)
