import re

from rest_framework import serializers

from .models import DeviceToken, UserAccount


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = [
            'uuid', 'full_name', 'phone_number', 'email', 'residency', 'preferred_currency',
            'country', 'kyc_status', 'notifications_enabled', 'created_at',
        ]
        read_only_fields = ['uuid', 'kyc_status', 'created_at']
        extra_kwargs = {
            'full_name': {'allow_null': True, 'required': False},
            'email': {'allow_null': True, 'required': False},
            'phone_number': {'allow_null': True, 'required': False},
        }

    def validate_full_name(self, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise serializers.ValidationError("Please enter your name.")
        return value

    def validate_phone_number(self, value):
        if value and not re.fullmatch(r'\+?\d{9,15}', value.replace(' ', '')):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value.replace(' ', '') if value else value

    def validate_country(self, value):
        value = (value or '').upper()
        if not re.fullmatch(r'[A-Z]{2}', value):
            raise serializers.ValidationError("Use a two-letter country code, e.g. TZ.")
        return value


class DeviceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=DeviceToken.PLATFORM_CHOICES)


class KycSubmitSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=('nida', 'passport'))
    document_number = serializers.CharField(max_length=40, trim_whitespace=True)

    def validate(self, data):
        number = data['document_number'].replace(' ', '').replace('-', '').upper()
        if data['document_type'] == 'nida':
            if not re.fullmatch(r'\d{20}', number):
                raise serializers.ValidationError({'document_number': ["A NIDA number has exactly 20 digits."]})
        elif not re.fullmatch(r'[A-Z0-9]{6,9}', number):
            raise serializers.ValidationError({'document_number': ["Enter a valid passport number."]})
        data['document_number'] = number
        return data
