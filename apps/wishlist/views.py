from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalogue.models import Itinerary
from apps.catalogue.serializers import ItinerarySerializer
from apps.catalogue.views import display_context, itinerary_queryset
from .models import WishlistItem


class WishlistView(APIView):
    """GET /api/users/wishlist/ — itineraries priced for the user's residency and currency."""

    def get(self, request):
        ids = WishlistItem.objects.filter(user=request.user).values_list('itinerary_id', flat=True)
        itineraries = itinerary_queryset().filter(id__in=ids)
        return Response(ItinerarySerializer(itineraries, many=True, context=display_context(request)).data)


class WishlistItemView(APIView):
    """POST/DELETE /api/users/wishlist/{itinerary_uuid}/ — both idempotent."""

    def post(self, request, itinerary_uuid):
        itinerary = get_object_or_404(Itinerary, uuid=itinerary_uuid, is_active=True)
        WishlistItem.objects.get_or_create(user=request.user, itinerary=itinerary)
        return Response({'message': 'Saved to wishlist'})

    def delete(self, request, itinerary_uuid):
        WishlistItem.objects.filter(user=request.user, itinerary__uuid=itinerary_uuid).delete()
        return Response({'message': 'Removed from wishlist'})
