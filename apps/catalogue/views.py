import calendar
from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.choices import AccommodationLevel, Residency
from apps.core.models import AppSetting
from utils.dates import today
from utils.api_docs import CURRENCY_PARAM, NOT_FOUND, RESIDENCY_PARAM, VALIDATION_ERROR
from utils.exceptions import BadRequest
from utils.money import is_supported
from utils.pagination_util import ItineraryPagination
from .models import Destination, Itinerary
from .serializers import DestinationSerializer, ItineraryPageSerializer, ItinerarySerializer, display_price


def itinerary_queryset():
    return (
        Itinerary.objects.filter(is_active=True)
        .select_related('operator', 'pricing')
        .prefetch_related('destination_links__destination', 'days', 'pricing__seasonal_adjustments')
    )


def display_context(request, residency=None, currency=None) -> dict:
    """residency/currency: query param → user profile → non_resident/USD."""
    user = request.user
    residency = residency or request.query_params.get('residency') or user.residency or Residency.NON_RESIDENT
    currency = (currency or request.query_params.get('currency') or user.preferred_currency or 'USD').upper()
    if residency not in Residency.values:
        raise BadRequest("Residency must be resident or non_resident.")
    if not is_supported(currency):
        raise BadRequest("That currency isn't supported.")
    return {'request': request, 'residency': residency, 'currency': currency, 'rates': {}}


def _int_param(params, name, low=None, high=None):
    raw = params.get(name)
    if raw in (None, ''):
        return None
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"{name} must be a whole number.")
    if (low is not None and value < low) or (high is not None and value > high):
        raise BadRequest(f"{name} is out of range.")
    return value


class ItineraryListView(APIView):
    """GET /api/itineraries/ — paginated, active only, featured first then newest."""

    @swagger_auto_schema(
        operation_summary="List trips",
        operation_description=(
            "Active trips, featured first, then by sort order and newest. 10 per page. "
            "Price filters compare against `display_price` (per adult, in the display currency)."
        ),
        manual_parameters=[
            openapi.Parameter('page', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, description="Page number, from 1."),
            openapi.Parameter('search', openapi.IN_QUERY, type=openapi.TYPE_STRING,
                              description="Matches the trip title or a destination name (case-insensitive)."),
            openapi.Parameter('destination', openapi.IN_QUERY, type=openapi.TYPE_STRING,
                              description="Exact destination name, as returned by `/api/itineraries/destinations/`."),
            openapi.Parameter('accommodation_level', openapi.IN_QUERY, type=openapi.TYPE_STRING,
                              enum=AccommodationLevel.values),
            openapi.Parameter('min_days', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, description="Shortest trip length."),
            openapi.Parameter('max_days', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, description="Longest trip length."),
            openapi.Parameter('min_price', openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Minimum `display_price`, minor units of the display currency."),
            openapi.Parameter('max_price', openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Maximum `display_price`, minor units of the display currency."),
            openapi.Parameter('month', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, minimum=1, maximum=12,
                              description="Only trips that can still be booked for the next occurrence of this "
                                          "month (allowing for the lead time plus 7 days)."),
            RESIDENCY_PARAM, CURRENCY_PARAM,
        ],
        responses={200: ItineraryPageSerializer, 400: VALIDATION_ERROR},
    )
    def get(self, request):
        params = request.query_params
        context = display_context(request)
        qs = itinerary_queryset()

        search = (params.get('search') or '').strip()
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(destinations__name__icontains=search))
        destination = params.get('destination')
        if destination:
            qs = qs.filter(destinations__name=destination)
        level = params.get('accommodation_level')
        if level:
            if level not in AccommodationLevel.values:
                raise BadRequest("Unknown accommodation level.")
            qs = qs.filter(accommodation_level=level)
        min_days = _int_param(params, 'min_days', low=0)
        max_days = _int_param(params, 'max_days', low=0)
        if min_days is not None:
            qs = qs.filter(duration_days__gte=min_days)
        if max_days is not None:
            qs = qs.filter(duration_days__lte=max_days)

        items = list(qs.distinct())

        # Price filters compare against display_price, which is computed in Python.
        min_price = _int_param(params, 'min_price', low=0)
        max_price = _int_param(params, 'max_price', low=0)
        for it in items:
            it._display_price = display_price(it, context['residency'], context['currency'], context['rates'])
        if min_price is not None:
            items = [it for it in items if it._display_price >= min_price]
        if max_price is not None:
            items = [it for it in items if it._display_price <= max_price]

        month = _int_param(params, 'month', low=1, high=12)
        if month is not None:
            items = self._bookable_in_month(items, month)

        paginator = ItineraryPagination()
        page = paginator.paginate_queryset(items, request, view=self)
        return paginator.get_paginated_response(ItinerarySerializer(page, many=True, context=context).data)

    @staticmethod
    def _bookable_in_month(items, month):
        """Keep trips whose next occurrence of `month` ends on/after today + lead time + 7 days."""
        now = today()
        year = now.year if month >= now.month else now.year + 1
        month_end = now.replace(year=year, month=month, day=calendar.monthrange(year, month)[1])
        default_lead = AppSetting.get().default_lead_time_days
        return [
            it for it in items
            if month_end >= now + timedelta(days=it.effective_lead_time_days(default_lead) + 7)
        ]


class ItineraryDetailView(APIView):
    """GET /api/itineraries/{uuid}/"""

    @swagger_auto_schema(
        operation_summary="Get a trip",
        operation_description="Full trip details with the day-by-day plan, prices and seasonal adjustments.",
        manual_parameters=[RESIDENCY_PARAM, CURRENCY_PARAM],
        responses={200: ItinerarySerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND},
    )
    def get(self, request, itinerary_uuid):
        itinerary = get_object_or_404(itinerary_queryset(), uuid=itinerary_uuid)
        return Response(ItinerarySerializer(itinerary, context=display_context(request)).data)


class DestinationListView(APIView):
    """GET /api/itineraries/destinations/"""

    @swagger_auto_schema(
        operation_summary="List destinations",
        operation_description="All destinations, alphabetically; use a `name` as the trip list's `destination` filter.",
        responses={200: DestinationSerializer(many=True)},
    )
    def get(self, request):
        return Response(DestinationSerializer(Destination.objects.all(), many=True).data)
