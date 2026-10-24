import os
import uuid as uuid_lib
from datetime import timedelta

from django.core.files.storage import default_storage
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from apps.core.choices import BookingStatus, GoalStatus, KycStatus, PaymentStatus
from apps.core.models import AppSetting, FxRate
from apps.core.tasks import refresh_fx_rates
from apps.goals.models import SavingsGoal
from apps.payments.models import Payment, Refund
from apps.userauth.models import KycDocument, UserAccount
from utils.dates import today as local_today
from ..access import has_permission
from ..serializers.system import AppSettingSerializer, FxOverrideSerializer, FxRateSerializer, UploadSerializer
from ..services import audit, snapshot
from .base import AdminAPIView, AdminViewMixin

SETTING_FIELDS = ['default_lead_time_days', 'missed_before_pause', 'min_payment_tzs', 'min_payment_other_major',
                  'reminder_days_before_due', 'pending_payment_timeout_minutes', 'packing_list']


def _by_currency(qs, field='amount'):
    return {row['currency']: row['total'] for row in qs.values('currency').annotate(total=Sum(field))}


class StatsView(AdminAPIView):
    """GET /api/admin/stats/?days=30 — numbers for the overview page. Money is per currency in minor units."""
    view_permission = 'reports.view'

    @swagger_auto_schema(operation_summary="Overview numbers")
    def get(self, request):
        try:
            days = max(7, min(365, int(request.query_params.get('days', 30))))
        except ValueError:
            days = 30
        now = timezone.now()
        since = now - timedelta(days=days)
        today = local_today()
        success = Payment.objects.filter(status=PaymentStatus.SUCCESS)

        series = (
            success.filter(settled_at__gte=since)
            .annotate(day=TruncDate('settled_at')).values('day', 'currency')
            .annotate(total=Sum('amount'), count=Count('id')).order_by('day')
        )
        signups = (
            UserAccount.objects.filter(created_at__gte=since, is_staff=False)
            .annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id')).order_by('day')
        )
        goal_counts = dict(SavingsGoal.objects.values_list('status').annotate(n=Count('id')))

        return Response({
            'days': days,
            'users': {
                'total': UserAccount.objects.filter(is_staff=False).count(),
                'new': UserAccount.objects.filter(is_staff=False, created_at__gte=since).count(),
                'residents': UserAccount.objects.filter(is_staff=False, residency='resident').count(),
                'non_residents': UserAccount.objects.filter(is_staff=False, residency='non_resident').count(),
            },
            'goals': {s: goal_counts.get(s, 0) for s in GoalStatus.values},
            'collected': _by_currency(success),
            'collected_in_period': _by_currency(success.filter(settled_at__gte=since)),
            'outstanding': _by_currency(
                SavingsGoal.objects.filter(status__in=(GoalStatus.ACTIVE, GoalStatus.PAUSED)),
                field='total_amount',
            ),
            'outstanding_paid': _by_currency(
                SavingsGoal.objects.filter(status__in=(GoalStatus.ACTIVE, GoalStatus.PAUSED)),
                field='amount_paid',
            ),
            'payments': {
                'pending': Payment.objects.filter(status=PaymentStatus.PENDING).count(),
                'failed_in_period': Payment.objects.filter(status=PaymentStatus.FAILED, created_at__gte=since).count(),
                'success_in_period': success.filter(settled_at__gte=since).count(),
            },
            'refunds': {
                'open': Refund.objects.filter(status__in=('pending', 'processing', 'failed')).count(),
                'failed': Refund.objects.filter(status='failed').count(),
                'open_amount': _by_currency(Refund.objects.filter(status__in=('pending', 'processing', 'failed'))),
            },
            'kyc_pending': KycDocument.objects.filter(status=KycStatus.PENDING).count(),
            'bookings': {
                'total': Booking.objects.count(),
                'upcoming': Booking.objects.filter(status=BookingStatus.CONFIRMED, travel_date__gte=today).count(),
                'next_30_days': Booking.objects.filter(
                    status=BookingStatus.CONFIRMED, travel_date__gte=today,
                    travel_date__lte=today + timedelta(days=30)).count(),
            },
            'collections_series': [
                {'date': row['day'].isoformat(), 'currency': row['currency'], 'amount': row['total'],
                 'count': row['count']} for row in series
            ],
            'signups_series': [{'date': row['day'].isoformat(), 'count': row['count']} for row in signups],
            'top_itineraries': list(
                SavingsGoal.objects.exclude(status=GoalStatus.DRAFT)
                .values('itinerary__uuid', 'itinerary__title').annotate(goals=Count('id'))
                .order_by('-goals')[:5]
                .values('itinerary__uuid', 'itinerary__title', 'goals')
            ),
        })


class FxRateViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = FxRateSerializer
    view_permission = 'fx.view'
    manage_permission = 'fx.manage'
    filterset_fields = ['from_currency', 'source']
    ordering_fields = ['fetched_at']

    def get_queryset(self):
        return FxRate.objects.all()

    @swagger_auto_schema(operation_summary="Rates in use now (newest per currency)",
                         responses={200: FxRateSerializer(many=True)})
    @action(detail=False, methods=['get'])
    def current(self, request):
        latest = []
        for code in FxRate.objects.values_list('from_currency', flat=True).distinct():
            rate = FxRate.objects.filter(from_currency=code, to_currency='TZS').order_by('-fetched_at').first()
            if rate:
                latest.append(rate)
        return Response(FxRateSerializer(sorted(latest, key=lambda r: r.from_currency), many=True).data)

    @swagger_auto_schema(operation_summary="Set a rate by hand", request_body=FxOverrideSerializer,
                         responses={201: FxRateSerializer})
    def create(self, request, *args, **kwargs):
        data = FxOverrideSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rate = FxRate.objects.create(**data.validated_data, to_currency='TZS', source=f'manual:{request.user.pk}',
                                     fetched_at=timezone.now())
        audit(request, 'fx.override', rate, after=snapshot(rate, ['from_currency', 'numerator', 'denominator']))
        return Response(FxRateSerializer(rate).data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(operation_summary="Fetch rates from the provider now", request_body=None)
    @action(detail=False, methods=['post'])
    def refresh(self, request):
        result = refresh_fx_rates.delay()
        audit(request, 'fx.refresh', target_type='fxrate')
        return Response({'queued': True, 'task_id': result.id}, status=status.HTTP_202_ACCEPTED)


class AppSettingView(AdminAPIView):
    view_permission = 'settings.view'
    manage_permission = 'settings.manage'

    @swagger_auto_schema(operation_summary="Business rules", responses={200: AppSettingSerializer})
    def get(self, request):
        return Response(AppSettingSerializer(AppSetting.get()).data)

    @swagger_auto_schema(operation_summary="Change business rules", request_body=AppSettingSerializer,
                         responses={200: AppSettingSerializer})
    def patch(self, request):
        setting = AppSetting.get()
        before = snapshot(setting, SETTING_FIELDS)
        serializer = AppSettingSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        setting = serializer.save()
        audit(request, 'settings.update', setting, target_id='1', before=before,
              after=snapshot(setting, SETTING_FIELDS))
        return Response(serializer.data)


UPLOAD_PERMISSIONS = {'itineraries': 'catalogue.manage', 'destinations': 'catalogue.manage',
                      'documents': 'bookings.manage'}
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.pdf'}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class UploadView(AdminAPIView):
    """POST /api/admin/uploads/ (multipart: file, folder) → {"url": "..."} for images and trip documents."""
    parser_classes = [MultiPartParser, FormParser]

    @swagger_auto_schema(operation_summary="Upload an image or PDF", request_body=UploadSerializer)
    def post(self, request):
        data = UploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        folder = data.validated_data['folder']
        if not has_permission(request.user, UPLOAD_PERMISSIONS[folder]):
            raise PermissionDenied("You don't have permission to do this.")
        upload = data.validated_data['file']
        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response({'file': ["Upload a JPG, PNG, WebP or PDF."]}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > MAX_UPLOAD_BYTES:
            return Response({'file': ["Files can be at most 10 MB."]}, status=status.HTTP_400_BAD_REQUEST)
        path = default_storage.save(f'admin/{folder}/{uuid_lib.uuid4().hex}{ext}', upload)
        url = request.build_absolute_uri(default_storage.url(path))
        audit(request, 'upload.create', target_type='upload', target_id=path, label=upload.name)
        return Response({'url': url}, status=status.HTTP_201_CREATED)
