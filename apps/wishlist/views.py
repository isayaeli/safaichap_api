from django.shortcuts import get_object_or_404
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalogue.models import Itinerary
from apps.catalogue.serializers import ItinerarySerializer
from apps.catalogue.views import display_context, itinerary_queryset
from utils.api_docs import CURRENCY_PARAM, NOT_FOUND, RESIDENCY_PARAM, VALIDATION_ERROR, MessageSerializer
from .models import WishlistItem


class WishlistView(APIView):
    """GET /api/users/wishlist/ — itineraries priced for the user's residency and currency."""

    @swagger_auto_schema(
        operation_summary="List saved trips",
        operation_description="Every saved trip that is still active, priced like the trip list. Not paginated.",
        manual_parameters=[RESIDENCY_PARAM, CURRENCY_PARAM],
        responses={200: ItinerarySerializer(many=True), 400: VALIDATION_ERROR},
    )
    def get(self, request):
        ids = WishlistItem.objects.filter(user=request.user).values_list('itinerary_id', flat=True)
        itineraries = itinerary_queryset().filter(id__in=ids)
        return Response(ItinerarySerializer(itineraries, many=True, context=display_context(request)).data)


class WishlistItemView(APIView):
    """POST/DELETE /api/users/wishlist/{itinerary_uuid}/ — both idempotent."""

    @swagger_auto_schema(
        operation_summary="Save a trip",
        operation_description="Idempotent: saving a trip twice is fine.",
        responses={200: MessageSerializer, 404: NOT_FOUND},
    )
    def post(self, request, itinerary_uuid):
        itinerary = get_object_or_404(Itinerary, uuid=itinerary_uuid, is_active=True)
        WishlistItem.objects.get_or_create(user=request.user, itinerary=itinerary)
        return Response({'message': 'Saved to wishlist'})

    @swagger_auto_schema(
        operation_summary="Remove a saved trip",
        operation_description="Idempotent: removing a trip that isn't saved still succeeds.",
        responses={200: MessageSerializer},
    )
    def delete(self, request, itinerary_uuid):
        WishlistItem.objects.filter(user=request.user, itinerary__uuid=itinerary_uuid).delete()
        return Response({'message': 'Removed from wishlist'})
