from rest_framework import serializers

from .models import Booking, TripDocument


class TripDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripDocument
        fields = ['type', 'title', 'url', 'content']


class BookingSerializer(serializers.ModelSerializer):
    goal_uuid = serializers.UUIDField(source='goal.uuid', read_only=True)
    itinerary_uuid = serializers.UUIDField(source='goal.itinerary.uuid', read_only=True)
    itinerary_title = serializers.CharField(source='goal.itinerary.title', read_only=True)
    documents = TripDocumentSerializer(many=True, read_only=True)
    operator_contact = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'uuid', 'goal_uuid', 'itinerary_uuid', 'itinerary_title', 'confirmation_code', 'status',
            'travel_date', 'documents', 'operator_contact', 'created_at',
        ]

    def get_operator_contact(self, obj):
        operator = obj.goal.itinerary.operator
        return {
            'name': operator.name,
            'phone_number': operator.phone_number or None,
            'email': operator.email or None,
            'whatsapp': operator.whatsapp or None,
        }
