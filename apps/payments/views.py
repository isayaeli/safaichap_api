import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from utils import card_gateway, clickpesa
from .models import Payment
from .serializers import InitiatePaymentSerializer, PaymentSerializer
from .services import card_amount_matches, initiate_payment, settle_payment

logger = logging.getLogger(__name__)


class InitiatePaymentView(APIView):
    """POST /api/payments/initiate/ — always 201 with the (pending or failed) payment."""
    throttle_scope = 'payments'

    def post(self, request):
        serializer = InitiatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = initiate_payment(request.user, serializer.validated_data)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentListView(APIView):
    """GET /api/payments/ — the user's payments, newest first."""

    def get(self, request):
        payments = Payment.objects.filter(user=request.user).select_related('goal')
        return Response(PaymentSerializer(payments, many=True).data)


class PaymentDetailView(APIView):
    """GET /api/payments/{uuid}/ — polled by the app every 3 s while pending."""

    def get(self, request, payment_uuid):
        payment = get_object_or_404(Payment.objects.select_related('goal'), uuid=payment_uuid, user=request.user)
        return Response(PaymentSerializer(payment).data)


class ClickPesaWebhookView(APIView):
    """POST /api/payments/webhooks/clickpesa/?secret=… (no auth; shared-secret verified)."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'webhooks'

    def post(self, request):
        if not clickpesa.verify_webhook(request):
            return Response({"detail": "Invalid signature."}, status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data if isinstance(request.data, dict) else {}
        data = payload.get("data") or {}
        order_reference = data.get("orderReference")
        provider_status = (data.get("status") or "").upper()
        if not order_reference or not provider_status:
            return Response({"detail": "Invalid webhook payload."}, status=status.HTTP_400_BAD_REQUEST)

        if provider_status in clickpesa.SUCCESS_STATUSES:
            settle_payment(order_reference, True,
                           provider_reference=data.get("paymentReference") or data.get("id"),
                           provider_txn_id=data.get("id"), raw=payload)
        elif provider_status in clickpesa.FAILED_STATUSES:
            settle_payment(order_reference, False, provider_txn_id=data.get("id"),
                           failure_reason="The payment was declined or cancelled on your phone.", raw=payload)
        else:
            logger.info("ClickPesa webhook %s with non-final status %s", order_reference, provider_status)
        return Response({"status": "received"})


class CardWebhookView(APIView):
    """POST /api/payments/webhooks/card/ (Flutterwave; `verif-hash` header verified)."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'webhooks'

    def post(self, request):
        if not card_gateway.verify_webhook(request):
            return Response({"detail": "Invalid signature."}, status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data if isinstance(request.data, dict) else {}
        data = payload.get("data") or {}
        order_reference = data.get("tx_ref")
        if not order_reference:
            return Response({"detail": "Invalid webhook payload."}, status=status.HTTP_400_BAD_REQUEST)

        # Don't trust the webhook body for the outcome: confirm with the gateway.
        record = card_gateway.verify_by_reference(order_reference)
        payment = Payment.objects.filter(order_reference=order_reference).first()
        if record and payment:
            fw_status = (record.get("status") or "").lower()
            txn_id = str(record.get("id") or "") or None
            if fw_status in card_gateway.SUCCESS_STATUSES and card_amount_matches(payment, record):
                settle_payment(order_reference, True, provider_reference=record.get("flw_ref") or txn_id,
                               provider_txn_id=txn_id, raw=payload)
            elif fw_status in card_gateway.FAILED_STATUSES:
                settle_payment(order_reference, False, provider_txn_id=txn_id,
                               failure_reason="Your card payment was declined.", raw=payload)
        return Response({"status": "received"})
