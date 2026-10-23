import re

from rest_framework import serializers

from apps.core.choices import MOBILE_MONEY_METHODS, PaymentMethod
from utils.money import CURRENCY_CHOICES
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    goal_uuid = serializers.UUIDField(source='goal.uuid', read_only=True)
    goal_title = serializers.CharField(source='goal.title', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'uuid', 'goal_uuid', 'goal_title', 'amount', 'currency', 'method', 'phone_number',
            'provider_reference', 'status', 'failure_reason', 'receipt_number', 'checkout_url', 'created_at',
        ]
        extra_kwargs = {
            'status': {'help_text': "`pending` until the provider confirms; poll the payment until it changes."},
            'checkout_url': {'help_text': "Card payments: open this page to pay."},
            'failure_reason': {'help_text': "Safe to show to the user."},
        }


class InitiatePaymentSerializer(serializers.Serializer):
    goal_uuid = serializers.UUIDField()
    amount = serializers.IntegerField(
        min_value=1, help_text="Minor units of `currency`; at least the app's minimum payment.")
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES, help_text="Must match the goal's currency.")
    method = serializers.ChoiceField(
        choices=PaymentMethod.choices, help_text="Mobile money methods are TZS only; `card` opens a checkout page.")
    order_reference = serializers.CharField(
        max_length=64, help_text="Client-generated idempotency key, 8–64 letters/digits. Retrying with the same "
                                 "reference returns the original payment instead of charging again.")
    phone_number = serializers.CharField(
        max_length=12, required=False, allow_null=True, allow_blank=True,
        help_text="Required for mobile money: `255` + 9 digits, e.g. `255712345678`.")

    def validate_order_reference(self, value):
        if not re.fullmatch(r'[A-Za-z0-9]{8,64}', value):
            raise serializers.ValidationError("Invalid payment reference.")
        return value

    def validate(self, data):
        phone = (data.get('phone_number') or '').strip()
        if data['method'] in MOBILE_MONEY_METHODS:
            if not re.fullmatch(r'255[67]\d{8}', phone):
                raise serializers.ValidationError({'phone_number': ["Enter a valid mobile money number."]})
        data['phone_number'] = phone or None
        return data
