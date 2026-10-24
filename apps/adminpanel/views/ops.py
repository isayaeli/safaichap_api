import csv

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.bookings.models import Booking, TripDocument
from apps.core.choices import GoalStatus, KycStatus, NotificationType, PaymentStatus
from apps.core.models import AppSetting
from apps.goals.models import SavingsGoal
from apps.goals.services.goals import cancel_goal, reschedule_goal
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.payments.models import Payment, Refund
from apps.payments.services import process_refund, reconcile_payment
from apps.userauth.models import KycDocument, UserAccount
from utils.exceptions import Conflict
from ..access import has_permission
from ..models import Broadcast
from ..serializers.ops import (
    AdminUserDetailSerializer, AdminUserSerializer, BookingDetailSerializer, BookingSerializer,
    BookingUpdateSerializer, BroadcastCreateSerializer, BroadcastSerializer, GoalDetailSerializer,
    GoalListSerializer, GoalReasonSerializer, GoalRescheduleSerializer, KycDocumentSerializer, KycReviewSerializer,
    NotificationSerializer, PaymentDetailSerializer, PaymentSerializer, RefundCloseSerializer, RefundSerializer,
    TripDocumentSerializer,
)
from ..services import audit, snapshot
from ..tasks import send_broadcast
from .base import AdminViewMixin

USER_FIELDS = ['full_name', 'phone_number', 'email', 'residency', 'preferred_currency', 'country',
               'notifications_enabled', 'is_active']
GOAL_FIELDS = ['status', 'travel_date', 'pay_by_date', 'frequency', 'amount_paid', 'total_amount',
               'consecutive_missed', 'cancellation_reason']


# ── Customers & KYC ────────────────────────────────────────────────────

class UserViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                  viewsets.GenericViewSet):
    lookup_field = 'uuid'
    view_permission = 'users.view'
    manage_permission = 'users.manage'
    action_permissions = {'export': 'users.export'}
    http_method_names = ['get', 'patch']
    search_fields = ['full_name', 'phone_number', 'email', 'username']
    filterset_fields = ['residency', 'kyc_status', 'is_active', 'is_staff', 'preferred_currency', 'country']
    ordering_fields = ['created_at', 'last_login', 'full_name', 'goals_count']

    def get_queryset(self):
        return UserAccount.objects.annotate(
            goals_count=Count('goals', distinct=True),
            active_goals_count=Count('goals', filter=Q(goals__status=GoalStatus.ACTIVE), distinct=True),
        ).order_by('-created_at')

    def get_serializer_class(self):
        return AdminUserDetailSerializer if self.action == 'retrieve' else AdminUserSerializer

    def perform_update(self, serializer):
        user = serializer.instance
        if user.pk == self.request.user.pk and serializer.validated_data.get('is_active') is False:
            raise Conflict("You can't disable your own account.")
        before = snapshot(user, USER_FIELDS)
        user = serializer.save()
        audit(self.request, 'user.update', user, before=before, after=snapshot(user, USER_FIELDS))

    @swagger_auto_schema(operation_summary="Export customers as CSV (same filters as the list)")
    @action(detail=False, methods=['get'])
    def export(self, request):
        users = self.filter_queryset(self.get_queryset())
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="safarichap-users.csv"'
        writer = csv.writer(response)
        columns = ['uuid', 'full_name', 'phone_number', 'email', 'residency', 'preferred_currency', 'country',
                   'kyc_status', 'is_active', 'goals_count', 'active_goals_count', 'created_at', 'last_login']
        writer.writerow(columns)
        for u in users.iterator():
            writer.writerow([getattr(u, c) for c in columns])
        audit(request, 'user.export', target_type='useraccount', label=f"{users.count()} users")
        return response


class KycViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = KycDocumentSerializer
    lookup_field = 'uuid'
    view_permission = 'kyc.view'
    manage_permission = 'kyc.review'
    filterset_fields = ['status', 'document_type']
    search_fields = ['user__full_name', 'user__phone_number', 'user__email']
    ordering_fields = ['created_at', 'reviewed_at']

    def get_queryset(self):
        return KycDocument.objects.select_related('user', 'reviewed_by')

    def _review(self, request, approve: bool):
        data = KycReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        note = data.validated_data.get('note', '').strip()
        with transaction.atomic():
            doc = KycDocument.objects.select_for_update().select_related('user').get(pk=self.get_object().pk)
            if doc.status != KycStatus.PENDING:
                raise Conflict("This document has already been reviewed.")
            doc.status = KycStatus.VERIFIED if approve else KycStatus.REJECTED
            doc.review_note = note
            doc.reviewed_at = timezone.now()
            doc.reviewed_by = request.user
            doc.save(update_fields=['status', 'review_note', 'reviewed_at', 'reviewed_by', 'updated_at'])
            UserAccount.objects.filter(pk=doc.user_id).update(kyc_status=doc.status)
            if approve:
                notify(doc.user, "Identity verified", "Thanks! Your ID has been verified.",
                       NotificationType.KYC_VERIFIED)
            else:
                notify(doc.user, "Please check your ID",
                       note or "We couldn't verify your ID document. Please submit it again.",
                       NotificationType.KYC_REJECTED)
            audit(request, 'kyc.approve' if approve else 'kyc.reject', doc, label=str(doc.user),
                  after={'status': doc.status, 'note': note})
        return Response(KycDocumentSerializer(doc).data)

    @swagger_auto_schema(request_body=KycReviewSerializer, responses={200: KycDocumentSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, uuid=None):
        return self._review(request, True)

    @swagger_auto_schema(request_body=KycReviewSerializer, responses={200: KycDocumentSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, uuid=None):
        return self._review(request, False)


# ── Goals ──────────────────────────────────────────────────────────────

class GoalViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_field = 'uuid'
    view_permission = 'goals.view'
    manage_permission = 'goals.manage'
    search_fields = ['title', 'user__full_name', 'user__phone_number', 'user__email', 'itinerary__title']
    filterset_fields = {
        'status': ['exact', 'in'], 'currency': ['exact'], 'itinerary__uuid': ['exact'], 'user__uuid': ['exact'],
        'travel_date': ['gte', 'lte'], 'pay_by_date': ['gte', 'lte'], 'created_at': ['gte', 'lte'],
    }
    ordering_fields = ['created_at', 'travel_date', 'pay_by_date', 'amount_paid', 'total_amount']

    def get_queryset(self):
        qs = SavingsGoal.objects.select_related('user', 'itinerary', 'itinerary__operator')
        if self.action == 'retrieve':
            qs = qs.prefetch_related('travellers', 'installments', 'payments__user', 'payments__goal',
                                     'refunds__user', 'refunds__goal').select_related('booking')
        return qs

    def get_serializer_class(self):
        return GoalDetailSerializer if self.action == 'retrieve' else GoalListSerializer

    def _detail(self, goal):
        return Response(GoalDetailSerializer(self.get_queryset().get(pk=goal.pk)).data)

    def _set_status(self, request, allowed, new_status, action_name, title, message):
        reason = GoalReasonSerializer(data=request.data)
        reason.is_valid(raise_exception=True)
        with transaction.atomic():
            goal = SavingsGoal.objects.select_for_update().select_related('user').get(pk=self.get_object().pk)
            if goal.status not in allowed:
                raise Conflict(f"A {goal.status} goal can't be changed this way.")
            before = snapshot(goal, GOAL_FIELDS)
            goal.status = new_status
            if new_status == GoalStatus.ACTIVE:
                goal.consecutive_missed = 0
            goal.save(update_fields=['status', 'consecutive_missed', 'updated_at'])
            audit(request, action_name, goal, before=before,
                  after={**snapshot(goal, GOAL_FIELDS), 'reason': reason.validated_data.get('reason', '')})
            notify(goal.user, title, message.format(title=goal.title), NotificationType.GOAL_PAUSED
                   if new_status == GoalStatus.PAUSED else NotificationType.ANNOUNCEMENT, goal)
        return self._detail(goal)

    @swagger_auto_schema(request_body=GoalReasonSerializer, responses={200: GoalDetailSerializer})
    @action(detail=True, methods=['post'])
    def pause(self, request, uuid=None):
        return self._set_status(request, (GoalStatus.ACTIVE,), GoalStatus.PAUSED, 'goal.pause',
                                "Goal paused", "{title} has been paused by our team. Contact support for help.")

    @swagger_auto_schema(request_body=GoalReasonSerializer, responses={200: GoalDetailSerializer})
    @action(detail=True, methods=['post'])
    def resume(self, request, uuid=None):
        return self._set_status(request, (GoalStatus.PAUSED,), GoalStatus.ACTIVE, 'goal.resume',
                                "Goal resumed", "{title} is active again.")

    @swagger_auto_schema(request_body=GoalRescheduleSerializer, responses={200: GoalDetailSerializer})
    @action(detail=True, methods=['post'])
    def reschedule(self, request, uuid=None):
        goal = self.get_object()
        data = GoalRescheduleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        before = snapshot(goal, GOAL_FIELDS)
        with transaction.atomic():
            goal = reschedule_goal(goal.user, goal.uuid, data.validated_data['travel_date'],
                                   data.validated_data.get('frequency'))
            audit(request, 'goal.reschedule', goal, before=before, after=snapshot(goal, GOAL_FIELDS))
            notify(goal.user, "Trip rescheduled",
                   f"{goal.title} now travels on {goal.travel_date:%d %b %Y}. Your installments were updated.",
                   NotificationType.ANNOUNCEMENT, goal)
        return self._detail(goal)

    @swagger_auto_schema(request_body=GoalReasonSerializer, responses={200: GoalDetailSerializer})
    @action(detail=True, methods=['post'])
    def cancel(self, request, uuid=None):
        goal = self.get_object()
        data = GoalReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        before = snapshot(goal, GOAL_FIELDS)
        with transaction.atomic():
            quote = cancel_goal(goal.user, goal.uuid, data.validated_data.get('reason'))
            goal.refresh_from_db()
            audit(request, 'goal.cancel', goal, before=before, after={**snapshot(goal, GOAL_FIELDS), **quote})
        return self._detail(goal)


# ── Payments & refunds ─────────────────────────────────────────────────

class PaymentViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_field = 'uuid'
    view_permission = 'payments.view'
    action_permissions = {'reconcile': 'payments.reconcile'}
    search_fields = ['order_reference', 'receipt_number', 'provider_reference', 'phone_number',
                     'user__full_name', 'user__phone_number', 'goal__title']
    filterset_fields = {
        'status': ['exact', 'in'], 'currency': ['exact'], 'method': ['exact'], 'provider': ['exact'],
        'user__uuid': ['exact'], 'goal__uuid': ['exact'], 'created_at': ['gte', 'lte'],
    }
    ordering_fields = ['created_at', 'amount', 'settled_at']

    def get_queryset(self):
        return Payment.objects.select_related('user', 'goal')

    def get_serializer_class(self):
        return PaymentDetailSerializer if self.action == 'retrieve' else PaymentSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, 'swagger_fake_view', False):
            context['can_view_raw'] = has_permission(self.request.user, 'payments.view_raw')
        return context

    @swagger_auto_schema(request_body=None, responses={200: PaymentDetailSerializer})
    @action(detail=True, methods=['post'])
    def reconcile(self, request, uuid=None):
        """Asks the provider for this pending payment's status now (instead of waiting for the 2-minute task)."""
        payment = self.get_object()
        if payment.status != PaymentStatus.PENDING:
            raise Conflict("Only pending payments can be reconciled.")
        reconcile_payment(payment, AppSetting.get().pending_payment_timeout_minutes)
        payment.refresh_from_db()
        audit(request, 'payment.reconcile', payment, after={'status': payment.status})
        return Response(PaymentDetailSerializer(payment, context=self.get_serializer_context()).data)


class RefundViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = RefundSerializer
    lookup_field = 'uuid'
    view_permission = 'refunds.view'
    manage_permission = 'refunds.manage'
    search_fields = ['order_reference', 'provider_reference', 'phone_number', 'user__full_name', 'goal__title']
    filterset_fields = {'status': ['exact', 'in'], 'currency': ['exact'], 'user__uuid': ['exact'],
                        'created_at': ['gte', 'lte']}
    ordering_fields = ['created_at', 'amount', 'processed_at']

    def get_queryset(self):
        return Refund.objects.select_related('user', 'goal')

    @swagger_auto_schema(request_body=None, responses={200: RefundSerializer})
    @action(detail=True, methods=['post'])
    def process(self, request, uuid=None):
        """Sends a pending or failed refund to the provider now (also after the automatic retries ran out)."""
        refund = self.get_object()
        if refund.status not in ('pending', 'failed'):
            raise Conflict("Only pending or failed refunds can be sent.")
        process_refund(refund.pk)
        refund.refresh_from_db()
        audit(request, 'refund.process', refund, after={'status': refund.status,
                                                        'failure_reason': refund.failure_reason})
        return Response(RefundSerializer(refund).data)

    @swagger_auto_schema(request_body=RefundCloseSerializer, responses={200: RefundSerializer})
    @action(detail=True, methods=['post'], url_path='mark-completed')
    def mark_completed(self, request, uuid=None):
        """For refunds paid out by hand outside the providers' APIs."""
        data = RefundCloseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            refund = Refund.objects.select_for_update().select_related('goal').get(pk=self.get_object().pk)
            if refund.status == 'completed':
                raise Conflict("This refund is already completed.")
            before = snapshot(refund, ['status', 'provider_reference'])
            refund.status = 'completed'
            refund.provider_reference = data.validated_data['provider_reference']
            refund.processed_at = timezone.now()
            refund.failure_reason = None
            refund.save()
            if refund.goal.status == GoalStatus.CANCELLED:
                refund.goal.payments.filter(status=PaymentStatus.SUCCESS).update(
                    status=PaymentStatus.REFUNDED, updated_at=timezone.now())
            audit(request, 'refund.mark_completed', refund, before=before,
                  after=snapshot(refund, ['status', 'provider_reference']))
        return Response(RefundSerializer(refund).data)


# ── Bookings ───────────────────────────────────────────────────────────

class BookingViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_field = 'uuid'
    view_permission = 'bookings.view'
    manage_permission = 'bookings.manage'
    search_fields = ['confirmation_code', 'goal__title', 'goal__user__full_name', 'goal__user__phone_number',
                     'goal__itinerary__title']
    filterset_fields = {'status': ['exact'], 'travel_date': ['gte', 'lte'],
                        'goal__itinerary__operator__uuid': ['exact']}
    ordering_fields = ['created_at', 'travel_date']

    def get_queryset(self):
        return Booking.objects.select_related('goal', 'goal__user', 'goal__itinerary', 'goal__itinerary__operator') \
            .prefetch_related('documents')

    def get_serializer_class(self):
        return BookingDetailSerializer if self.action in ('retrieve', 'partial_update') else BookingSerializer

    @swagger_auto_schema(request_body=BookingUpdateSerializer, responses={200: BookingDetailSerializer})
    def partial_update(self, request, uuid=None):
        booking = self.get_object()
        data = BookingUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        before = snapshot(booking, ['status'])
        booking.status = data.validated_data['status']
        booking.save(update_fields=['status', 'updated_at'])
        audit(request, 'booking.update', booking, before=before, after=snapshot(booking, ['status']))
        return Response(BookingDetailSerializer(booking).data)

    @swagger_auto_schema(method='post', request_body=TripDocumentSerializer, responses={201: TripDocumentSerializer})
    @action(detail=True, methods=['post'])
    def documents(self, request, uuid=None):
        booking = self.get_object()
        serializer = TripDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = serializer.save(booking=booking)
        audit(request, 'booking.document_add', doc, label=f"{booking} · {doc.title}",
              after=snapshot(doc, ['type', 'title', 'url']))
        return Response(TripDocumentSerializer(doc).data, status=201)

    @swagger_auto_schema(request_body=None, responses={200: BookingDetailSerializer})
    @action(detail=True, methods=['post'])
    def notify(self, request, uuid=None):
        """Tells the traveller their trip documents changed."""
        booking = self.get_object()
        notify(booking.goal.user, "Trip documents updated",
               f"Your documents for {booking.goal.itinerary.title} ({booking.confirmation_code}) were updated.",
               NotificationType.BOOKING_UPDATED, booking.goal)
        audit(request, 'booking.notify', booking)
        return Response(BookingDetailSerializer(booking).data)


class TripDocumentViewSet(AdminViewMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = TripDocumentSerializer
    lookup_field = 'uuid'
    view_permission = 'bookings.view'
    manage_permission = 'bookings.manage'
    http_method_names = ['patch', 'delete']
    queryset = TripDocument.objects.select_related('booking')

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, ['type', 'title', 'url', 'content'])
        doc = serializer.save()
        audit(self.request, 'booking.document_update', doc, before=before,
              after=snapshot(doc, ['type', 'title', 'url', 'content']))

    def perform_destroy(self, doc):
        audit(self.request, 'booking.document_delete', doc, before=snapshot(doc, ['type', 'title', 'url']))
        doc.delete()


# ── Notifications ──────────────────────────────────────────────────────

class NotificationViewSet(AdminViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    view_permission = 'notifications.view'
    search_fields = ['title', 'message', 'user__full_name', 'user__phone_number']
    filterset_fields = {'type': ['exact'], 'is_read': ['exact'], 'user__uuid': ['exact'],
                        'created_at': ['gte', 'lte']}
    ordering_fields = ['created_at']

    def get_queryset(self):
        return Notification.objects.select_related('user')


def broadcast_recipients(data: dict):
    users = UserAccount.objects.filter(is_active=True, is_staff=False)
    audience = data['audience']
    if audience == 'residency':
        users = users.filter(residency=data['residency'])
    elif audience == 'goal_status':
        users = users.filter(goals__status=data['goal_status'])
    elif audience == 'users':
        users = UserAccount.objects.filter(uuid__in=data['user_uuids'], is_active=True)
    return users.distinct()


class BroadcastViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    view_permission = 'notifications.view'
    manage_permission = 'notifications.send'
    search_fields = ['title', 'message']
    ordering_fields = ['created_at']

    def get_queryset(self):
        return Broadcast.objects.select_related('sent_by')

    def get_serializer_class(self):
        return BroadcastCreateSerializer if self.action == 'create' else BroadcastSerializer

    @swagger_auto_schema(operation_summary="Send a notification to a group of customers",
                         operation_description="With `dry_run: true` only `recipients` is returned.",
                         request_body=BroadcastCreateSerializer, responses={201: BroadcastSerializer})
    def create(self, request, *args, **kwargs):
        data = BroadcastCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        user_ids = list(broadcast_recipients(values).values_list('id', flat=True))
        if values['dry_run']:
            return Response({'recipients': len(user_ids)})
        if not user_ids:
            raise Conflict("No customers match this audience.")
        audience = {'kind': values['audience']}
        for key in ('residency', 'goal_status'):
            if key in values:
                audience[key] = values[key]
        if 'user_uuids' in values:
            audience['user_uuids'] = [str(u) for u in values['user_uuids']]
        broadcast = Broadcast.objects.create(title=values['title'], message=values['message'], audience=audience,
                                             recipients=len(user_ids), sent_by=request.user)
        audit(request, 'notification.broadcast', broadcast, after={**audience, 'recipients': len(user_ids)})
        transaction.on_commit(lambda: send_broadcast.delay(broadcast.pk, user_ids))
        return Response(BroadcastSerializer(broadcast).data, status=201)
