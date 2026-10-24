from django.db.models import Count, ProtectedError
from rest_framework import viewsets

from apps.catalogue.models import Destination, Itinerary, Operator, RefundPolicy
from utils.exceptions import Conflict
from ..serializers.catalogue import (
    DestinationSerializer, ItineraryListSerializer, ItinerarySerializer, OperatorSerializer, RefundPolicySerializer,
)
from ..services import audit, snapshot
from .base import AdminViewMixin


class AuditedModelViewSet(AdminViewMixin, viewsets.ModelViewSet):
    """CRUD that writes an audit row per change. `audit_name` prefixes the action, e.g. `operator.update`."""
    lookup_field = 'uuid'
    audit_name = ''
    audit_fields = None
    protected_message = "This is still in use, so it can't be deleted."

    def perform_create(self, serializer):
        obj = serializer.save()
        audit(self.request, f'{self.audit_name}.create', obj, after=snapshot(obj, self.audit_fields))

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, self.audit_fields)
        obj = serializer.save()
        audit(self.request, f'{self.audit_name}.update', obj, before=before, after=snapshot(obj, self.audit_fields))

    def perform_destroy(self, obj):
        before = snapshot(obj, self.audit_fields)
        try:
            obj.delete()
        except ProtectedError:
            raise Conflict(self.protected_message)
        audit(self.request, f'{self.audit_name}.delete', target_type=obj._meta.model_name,
              target_id=str(obj.uuid), label=str(obj), before=before)


class CatalogueViewSet(AuditedModelViewSet):
    view_permission = 'catalogue.view'
    manage_permission = 'catalogue.manage'


class RefundPolicyViewSet(CatalogueViewSet):
    serializer_class = RefundPolicySerializer
    audit_name = 'refund_policy'
    search_fields = ['name']
    ordering_fields = ['name', 'created_at']
    pagination_class = None

    def get_queryset(self):
        return RefundPolicy.objects.annotate(operators_count=Count('operator')).order_by('-is_default', 'name')


class OperatorViewSet(CatalogueViewSet):
    serializer_class = OperatorSerializer
    audit_name = 'operator'
    protected_message = "This operator still has trips. Move or delete them first."
    search_fields = ['name', 'email', 'phone_number']
    ordering_fields = ['name', 'created_at', 'itineraries_count']

    def get_queryset(self):
        return Operator.objects.select_related('refund_policy') \
            .annotate(itineraries_count=Count('itineraries')).order_by('name')


class DestinationViewSet(CatalogueViewSet):
    serializer_class = DestinationSerializer
    audit_name = 'destination'
    search_fields = ['name', 'region']
    filterset_fields = ['region']
    ordering_fields = ['name', 'created_at', 'itineraries_count']

    def get_queryset(self):
        return Destination.objects.annotate(itineraries_count=Count('itineraries')).order_by('name')


class ItineraryViewSet(CatalogueViewSet):
    audit_name = 'itinerary'
    audit_fields = ['title', 'slug', 'summary', 'duration_days', 'accommodation_level', 'operator', 'is_active',
                    'is_featured', 'sort_order', 'lead_time_days', 'min_group_size', 'max_group_size',
                    'kyc_required', 'images', 'inclusions', 'exclusions']
    protected_message = "Customers have goals for this trip. Deactivate it instead."
    search_fields = ['title', 'slug', 'summary', 'operator__name']
    filterset_fields = {'is_active': ['exact'], 'is_featured': ['exact'], 'accommodation_level': ['exact'],
                        'operator__uuid': ['exact'], 'destinations__uuid': ['exact']}
    ordering_fields = ['title', 'created_at', 'sort_order', 'goals_count']

    def get_queryset(self):
        return Itinerary.objects.select_related('operator', 'pricing') \
            .prefetch_related('destination_links__destination', 'days', 'pricing__seasonal_adjustments') \
            .annotate(goals_count=Count('goals', distinct=True)).distinct()

    def get_serializer_class(self):
        return ItineraryListSerializer if self.action == 'list' else ItinerarySerializer

    def _priced_snapshot(self, obj):
        data = snapshot(obj, self.audit_fields)
        if hasattr(obj, 'pricing'):
            obj.pricing.refresh_from_db()
            data['pricing'] = obj.pricing.to_dict()
        return data

    def perform_create(self, serializer):
        obj = serializer.save()
        audit(self.request, 'itinerary.create', obj, after=self._priced_snapshot(obj))

    def perform_update(self, serializer):
        before = self._priced_snapshot(serializer.instance)
        obj = serializer.save()
        audit(self.request, 'itinerary.update', obj, before=before, after=self._priced_snapshot(obj))
