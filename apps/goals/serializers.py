from drf_yasg.utils import swagger_serializer_method
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
        extra_kwargs = {
            'amount': {'help_text': "Minor units of the goal currency."},
            'amount_paid': {'help_text': "Minor units of the goal currency."},
            'is_deposit': {'help_text': "The upfront deposit, due the day the goal is activated."},
        }


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
        extra_kwargs = {
            'total_amount': {'help_text': "Minor units of `currency`. Locked when the goal is activated."},
            'deposit_amount': {'help_text': "Minor units of `currency`."},
            'amount_paid': {'help_text': "Sum of successful payments, minor units of `currency`."},
            'pay_by_date': {'help_text': "Travel date minus the operator's lead time; the last installment is due by then."},
            'consecutive_missed': {'help_text': "Missed installments in a row; the goal pauses at the configured limit."},
            'custom_days': {'help_text': "Days between installments when `frequency` is `custom`."},
        }

    def _installments(self, obj):
        if not hasattr(obj, '_installments_cache'):
            obj._installments_cache = sorted(obj.installments.all(), key=lambda i: (i.due_date, i.position))
        return obj._installments_cache

    def _next_open(self, obj):
        if obj.status == GoalStatus.COMPLETED:
            return None
        return next_open_installment(self._installments(obj))

    @swagger_serializer_method(InstallmentSerializer(many=True))
    def get_installments(self, obj):
        return InstallmentSerializer(self._installments(obj), many=True).data

    @swagger_serializer_method(serializers.IntegerField(
        help_text="Still owed on the next open installment (minor units); 0 when nothing is due."))
    def get_installment_amount(self, obj):
        nxt = self._next_open(obj)
        return nxt.amount - nxt.amount_paid if nxt else 0

    @swagger_serializer_method(serializers.DateField(allow_null=True, help_text="Due date of the next open installment."))
    def get_next_due_date(self, obj):
        nxt = self._next_open(obj)
        return nxt.due_date.isoformat() if nxt else None

    @swagger_serializer_method(serializers.URLField(allow_null=True))
    def get_cover_image(self, obj):
        return obj.itinerary.cover_image

    @swagger_serializer_method(serializers.UUIDField(allow_null=True, help_text="Set once the goal is completed."))
    def get_booking_uuid(self, obj):
        booking = getattr(obj, 'booking', None)
        return str(booking.uuid) if booking else None


class PlanSerializer(serializers.Serializer):
    """Body for POST /api/goals/quote/ and POST /api/goals/."""
    itinerary_uuid = serializers.UUIDField()
    travellers = TravellerSerializer(many=True)
    travel_date = serializers.DateField(help_text="Must leave room for the operator's lead time.")
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES, help_text="The goal is saved and paid in this currency.")
    frequency = serializers.ChoiceField(choices=PaymentFrequency.choices, default=PaymentFrequency.MONTHLY)
    deposit_amount = serializers.IntegerField(
        min_value=0, default=0, help_text="Paid upfront, minor units of `currency`. Must be less than the total.")
    custom_days = serializers.IntegerField(
        min_value=1, max_value=365, default=30, allow_null=True,
        help_text="Days between installments; only used when `frequency` is `custom`.")
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, allow_null=True,
                                  help_text="Defaults to the trip title.")

    def validate_custom_days(self, value):
        return value or 30


class RescheduleSerializer(serializers.Serializer):
    travel_date = serializers.DateField()
    frequency = serializers.ChoiceField(choices=PaymentFrequency.choices, required=False, allow_null=True,
                                        help_text="Omit to keep the current frequency.")


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1000)


# ── Response shapes for the API docs (the views return plain dicts) ─────

class QuoteLineSerializer(serializers.Serializer):
    residency = serializers.ChoiceField(choices=Residency.choices)
    age_category = serializers.ChoiceField(choices=AgeCategory.choices)
    count = serializers.IntegerField()
    unit_price = serializers.IntegerField(help_text="Per person, season-adjusted, minor units of `currency`.")
    subtotal = serializers.IntegerField()


class QuoteInstallmentSerializer(serializers.Serializer):
    due_date = serializers.DateField()
    amount = serializers.IntegerField()
    is_deposit = serializers.BooleanField()


class QuoteSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES)
    total_amount = serializers.IntegerField(help_text="Minor units of `currency`.")
    deposit_amount = serializers.IntegerField()
    pay_by_date = serializers.DateField()
    season_label = serializers.CharField(allow_null=True, help_text="e.g. \"High season (+20%)\", or null.")
    lines = QuoteLineSerializer(many=True)
    installments = QuoteInstallmentSerializer(many=True, help_text="The schedule the goal would get today.")


class CancellationQuoteSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES)
    amount_paid = serializers.IntegerField()
    refund_percentage = serializers.IntegerField(help_text="From the operator's refund tiers, by days to travel.")
    processing_fee = serializers.IntegerField()
    refund_amount = serializers.IntegerField(help_text="amount_paid × refund_percentage − processing_fee.")
    policy = serializers.CharField(help_text="The policy text to show the user.")
