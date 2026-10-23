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


class InitiatePaymentSerializer(serializers.Serializer):
    goal_uuid = serializers.UUIDField()
    amount = serializers.IntegerField(min_value=1)
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES)
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    order_reference = serializers.CharField(max_length=64)
    phone_number = serializers.CharField(max_length=12, required=False, allow_null=True, allow_blank=True)

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
