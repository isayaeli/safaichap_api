"""Admin views of customers, KYC, goals, payments, refunds, bookings and notifications."""
from rest_framework import serializers

from apps.bookings.models import Booking, TripDocument
from apps.core.choices import BookingStatus, GoalStatus, PaymentFrequency, Residency
from apps.goals.models import Installment, SavingsGoal, Traveller
from apps.goals.services.goals import CANCELLABLE, cancellation_quote
from apps.notifications.models import Notification
from apps.payments.models import Payment, Refund
from apps.userauth.models import DeviceToken, KycDocument, UserAccount
from ..models import Broadcast


class UserRefSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminUserRef'
        model = UserAccount
        fields = ['uuid', 'full_name', 'phone_number', 'email']


class AdminUserSerializer(serializers.ModelSerializer):
    goals_count = serializers.IntegerField(read_only=True, default=0)
    active_goals_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminAdminUser'
        model = UserAccount
        fields = ['uuid', 'full_name', 'phone_number', 'email', 'residency', 'preferred_currency', 'country',
                  'kyc_status', 'notifications_enabled', 'is_active', 'is_staff', 'last_login', 'created_at',
                  'goals_count', 'active_goals_count']
        read_only_fields = ['uuid', 'kyc_status', 'is_staff', 'last_login', 'created_at']
        extra_kwargs = {'full_name': {'allow_null': True}, 'email': {'allow_null': True},
                        'phone_number': {'allow_null': True}}


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminDevice'
        model = DeviceToken
        fields = ['uuid', 'platform', 'notifications_enabled', 'created_at', 'updated_at']


class KycDocumentSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)
    reviewed_by = serializers.SerializerMethodField()

    class Meta:
        ref_name = 'AdminKycDocument'
        model = KycDocument
        fields = ['uuid', 'user', 'document_type', 'document_number', 'status', 'review_note', 'reviewed_at',
                  'reviewed_by', 'created_at']

    def get_reviewed_by(self, obj):
        return str(obj.reviewed_by) if obj.reviewed_by_id else None


class KycReviewSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminKycReview'

    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class InstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminInstallment'
        model = Installment
        fields = ['uuid', 'due_date', 'amount', 'amount_paid', 'status', 'is_deposit']


class TravellerSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminTraveller'
        model = Traveller
        fields = ['name', 'age_category', 'residency']


class GoalListSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)
    itinerary_uuid = serializers.UUIDField(source='itinerary.uuid', read_only=True)
    itinerary_title = serializers.CharField(source='itinerary.title', read_only=True)

    class Meta:
        ref_name = 'AdminGoalList'
        model = SavingsGoal
        fields = ['uuid', 'title', 'user', 'itinerary_uuid', 'itinerary_title', 'travel_date', 'pay_by_date',
                  'currency', 'total_amount', 'deposit_amount', 'amount_paid', 'frequency', 'status',
                  'consecutive_missed', 'created_at', 'activated_at', 'completed_at']


class PaymentSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)
    goal_uuid = serializers.UUIDField(source='goal.uuid', read_only=True)
    goal_title = serializers.CharField(source='goal.title', read_only=True)

    class Meta:
        ref_name = 'AdminPayment'
        model = Payment
        fields = ['uuid', 'user', 'goal_uuid', 'goal_title', 'amount', 'currency', 'method', 'phone_number',
                  'order_reference', 'provider', 'provider_reference', 'provider_txn_id', 'status',
                  'failure_reason', 'receipt_number', 'settled_at', 'created_at']


class PaymentDetailSerializer(PaymentSerializer):
    raw_webhook = serializers.SerializerMethodField()

    class Meta(PaymentSerializer.Meta):
        ref_name = 'AdminPaymentDetail'
        fields = PaymentSerializer.Meta.fields + ['raw_webhook']

    def get_raw_webhook(self, obj):
        return obj.raw_webhook if self.context.get('can_view_raw') else None


class RefundSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)
    goal_uuid = serializers.UUIDField(source='goal.uuid', read_only=True)
    goal_title = serializers.CharField(source='goal.title', read_only=True)

    class Meta:
        ref_name = 'AdminRefund'
        model = Refund
        fields = ['uuid', 'user', 'goal_uuid', 'goal_title', 'amount', 'currency', 'order_reference',
                  'phone_number', 'status', 'provider_reference', 'attempts', 'failure_reason', 'processed_at',
                  'created_at']


class RefundCloseSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminRefundClose'

    provider_reference = serializers.CharField(max_length=255, help_text="Reference of the manual payout.")


class GoalDetailSerializer(GoalListSerializer):
    travellers = TravellerSerializer(many=True, read_only=True)
    installments = InstallmentSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)
    booking_uuid = serializers.SerializerMethodField()
    cancellation_quote = serializers.SerializerMethodField()

    class Meta(GoalListSerializer.Meta):
        ref_name = 'AdminGoalDetail'
        fields = GoalListSerializer.Meta.fields + [
            'custom_days', 'cancellation_reason', 'locked_pricing_snapshot', 'travellers', 'installments',
            'payments', 'refunds', 'booking_uuid', 'cancellation_quote',
        ]

    def get_booking_uuid(self, obj):
        booking = getattr(obj, 'booking', None)
        return str(booking.uuid) if booking else None

    def get_cancellation_quote(self, obj):
        return cancellation_quote(obj) if obj.status in CANCELLABLE else None


class GoalRescheduleSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminGoalReschedule'

    travel_date = serializers.DateField()
    frequency = serializers.ChoiceField(choices=PaymentFrequency.choices, required=False, allow_null=True)


class GoalReasonSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminGoalReason'

    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class AdminUserDetailSerializer(AdminUserSerializer):
    goals = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    devices = DeviceSerializer(source='device_tokens', many=True, read_only=True)
    kyc_documents = serializers.SerializerMethodField()

    class Meta(AdminUserSerializer.Meta):
        ref_name = 'AdminAdminUserDetail'
        fields = AdminUserSerializer.Meta.fields + ['goals', 'payments', 'devices', 'kyc_documents']

    def get_goals(self, obj):
        goals = obj.goals.select_related('itinerary', 'user')[:50]
        return GoalListSerializer(goals, many=True).data

    def get_payments(self, obj):
        payments = obj.payments.select_related('goal', 'user')[:50]
        return PaymentSerializer(payments, many=True).data

    def get_kyc_documents(self, obj):
        docs = obj.kyc_documents.select_related('user', 'reviewed_by')
        return KycDocumentSerializer(docs, many=True).data


class TripDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminTripDocument'
        model = TripDocument
        fields = ['uuid', 'type', 'title', 'url', 'content', 'position', 'created_at']
        read_only_fields = ['uuid', 'created_at']


class BookingSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(source='goal.user', read_only=True)
    goal_uuid = serializers.UUIDField(source='goal.uuid', read_only=True)
    itinerary_title = serializers.CharField(source='goal.itinerary.title', read_only=True)
    operator_name = serializers.CharField(source='goal.itinerary.operator.name', read_only=True)
    travellers = serializers.IntegerField(source='goal.travellers.count', read_only=True)

    class Meta:
        ref_name = 'AdminBooking'
        model = Booking
        fields = ['uuid', 'confirmation_code', 'status', 'travel_date', 'user', 'goal_uuid', 'itinerary_title',
                  'operator_name', 'travellers', 'created_at']
        read_only_fields = ['uuid', 'confirmation_code', 'travel_date', 'created_at']


class BookingDetailSerializer(BookingSerializer):
    documents = TripDocumentSerializer(many=True, read_only=True)

    class Meta(BookingSerializer.Meta):
        ref_name = 'AdminBookingDetail'
        fields = BookingSerializer.Meta.fields + ['documents']


class BookingUpdateSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminBookingUpdate'

    status = serializers.ChoiceField(choices=BookingStatus.choices)


class NotificationSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)

    class Meta:
        ref_name = 'AdminNotification'
        model = Notification
        fields = ['uuid', 'user', 'title', 'message', 'type', 'is_read', 'created_at']


class BroadcastSerializer(serializers.ModelSerializer):
    sent_by = serializers.SerializerMethodField()

    class Meta:
        ref_name = 'AdminBroadcast'
        model = Broadcast
        fields = ['uuid', 'title', 'message', 'audience', 'recipients', 'sent_by', 'created_at']

    def get_sent_by(self, obj):
        return str(obj.sent_by) if obj.sent_by_id else None


AUDIENCE_KINDS = ('all', 'residency', 'goal_status', 'users')


class BroadcastCreateSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminBroadcastCreate'

    title = serializers.CharField(max_length=255)
    message = serializers.CharField(max_length=2000)
    audience = serializers.ChoiceField(choices=AUDIENCE_KINDS)
    residency = serializers.ChoiceField(choices=Residency.choices, required=False)
    goal_status = serializers.ChoiceField(choices=GoalStatus.choices, required=False)
    user_uuids = serializers.ListField(child=serializers.UUIDField(), required=False)
    dry_run = serializers.BooleanField(default=False, help_text="Only count the recipients.")

    def validate(self, data):
        needs = {'residency': 'residency', 'goal_status': 'goal_status', 'users': 'user_uuids'}
        field = needs.get(data['audience'])
        if field and not data.get(field):
            raise serializers.ValidationError({field: ["This field is required for this audience."]})
        return data
