from rest_framework import serializers

from apps.core.models import AppSetting, FxRate
from utils.money import CURRENCY_CHOICES


class FxRateSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminFxRate'
        model = FxRate
        fields = ['uuid', 'from_currency', 'to_currency', 'numerator', 'denominator', 'source', 'fetched_at']
        read_only_fields = ['uuid', 'to_currency', 'source', 'fetched_at']


class FxOverrideSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminFxOverride'

    from_currency = serializers.ChoiceField(choices=[c for c in CURRENCY_CHOICES if c[0] != 'TZS'])
    numerator = serializers.IntegerField(min_value=1, help_text="TZS per unit = numerator / denominator.")
    denominator = serializers.IntegerField(min_value=1, default=1)


class AppSettingSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminAppSetting'
        model = AppSetting
        fields = ['default_lead_time_days', 'missed_before_pause', 'min_payment_tzs', 'min_payment_other_major',
                  'reminder_days_before_due', 'pending_payment_timeout_minutes', 'packing_list', 'updated_at']
        read_only_fields = ['updated_at']

    def validate_missed_before_pause(self, value):
        if value < 1:
            raise serializers.ValidationError("Must be at least 1.")
        return value

    def validate_pending_payment_timeout_minutes(self, value):
        if value < 2:
            raise serializers.ValidationError("Must be at least 2 minutes.")
        return value


class UploadSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminUpload'

    file = serializers.FileField()
    folder = serializers.ChoiceField(choices=['itineraries', 'destinations', 'documents'])
