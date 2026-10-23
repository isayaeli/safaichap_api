from django.shortcuts import get_object_or_404
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.api_docs import NOT_FOUND
from .models import Booking
from .serializers import BookingSerializer


def bookings_for(user):
    return (
        Booking.objects.filter(goal__user=user)
        .select_related('goal__itinerary__operator')
        .prefetch_related('documents')
    )


class BookingListView(APIView):
    """GET /api/bookings/"""

    @swagger_auto_schema(
        operation_summary="List bookings",
        operation_description="Bookings from the user's completed goals, newest first, with trip documents "
                              "(voucher, operator contacts, packing list). Not paginated.",
        responses={200: BookingSerializer(many=True)},
    )
    def get(self, request):
        return Response(BookingSerializer(bookings_for(request.user), many=True).data)


class BookingDetailView(APIView):
    """GET /api/bookings/{uuid}/"""

    @swagger_auto_schema(operation_summary="Get a booking", responses={200: BookingSerializer, 404: NOT_FOUND})
    def get(self, request, booking_uuid):
        booking = get_object_or_404(bookings_for(request.user), uuid=booking_uuid)
        return Response(BookingSerializer(booking).data)
