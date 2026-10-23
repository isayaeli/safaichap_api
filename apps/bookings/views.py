from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking
from .serializers import BookingSerializer


def bookings_for(user):
    return (
        Booking.objects.filter(goal__user=user)
        .select_related('goal__itinerary__operator')
        .prefetch_related('documents')
    )


class BookingListView(APIView):
    def get(self, request):
        return Response(BookingSerializer(bookings_for(request.user), many=True).data)


class BookingDetailView(APIView):
    def get(self, request, booking_uuid):
        booking = get_object_or_404(bookings_for(request.user), uuid=booking_uuid)
        return Response(BookingSerializer(booking).data)
