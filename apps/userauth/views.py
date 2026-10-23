from django.db import transaction
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.choices import KycStatus
from .models import DeviceToken, KycDocument, UserAccount
from utils.api_docs import VALIDATION_ERROR, OkSerializer, rate_limit_note
from .serializers import DeviceTokenSerializer, KycResultSerializer, KycSubmitSerializer, UserSerializer


class CurrentUserAPIView(APIView):
    """GET/PATCH /api/users/me/ — the profile is created on first authenticated call."""
    throttle_scope = 'account'

    @swagger_auto_schema(
        operation_summary="Get my profile",
        operation_description="Creates the profile from the Firebase token on the first call.",
        responses={200: UserSerializer},
    )
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @swagger_auto_schema(
        operation_summary="Update my profile",
        operation_description="Send only the fields to change. `uuid`, `kyc_status` and `created_at` are read-only."
                              + rate_limit_note("10/min (account)"),
        request_body=UserSerializer,
        responses={200: UserSerializer, 400: VALIDATION_ERROR},
    )
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RegisterDeviceView(APIView):
    """POST /api/users/devices/ — upsert on token and reassign it to the current user."""
    throttle_scope = 'account'

    @swagger_auto_schema(
        operation_summary="Register a push device",
        operation_description="Call after sign-in and whenever the FCM token changes. If the token was registered "
                              "to another user it moves to this one, and notifications are re-enabled."
                              + rate_limit_note("10/min (account)"),
        request_body=DeviceTokenSerializer,
        responses={200: OkSerializer, 400: VALIDATION_ERROR},
    )
    def post(self, request):
        serializer = DeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DeviceToken.objects.update_or_create(
            token=serializer.validated_data['token'],
            defaults={
                'user': request.user,
                'platform': serializer.validated_data['platform'],
                'notifications_enabled': True,
            },
        )
        return Response({'ok': True})


class SubmitKycView(APIView):
    """POST /api/users/kyc/ — stores the document (encrypted) for admin review."""
    throttle_scope = 'kyc'

    @swagger_auto_schema(
        operation_summary="Submit an ID document (KYC)",
        operation_description=(
            "Some trips need the traveller's NIDA or passport number after booking. The number is stored "
            "encrypted and the user's `kyc_status` becomes `pending` until an admin reviews it. If the user is "
            "already verified, nothing is stored."
            + rate_limit_note("5/min (KYC)")
        ),
        request_body=KycSubmitSerializer,
        responses={200: KycResultSerializer, 400: VALIDATION_ERROR},
    )
    def post(self, request):
        serializer = KycSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user

        if user.kyc_status == KycStatus.VERIFIED:
            return Response({'message': "Your identity is already verified.", 'kyc_status': user.kyc_status})

        with transaction.atomic():
            KycDocument.objects.create(user=user, status=KycStatus.PENDING, **serializer.validated_data)
            UserAccount.objects.filter(pk=user.pk).update(kyc_status=KycStatus.PENDING)

        return Response(
            {'message': "Thanks! We're reviewing your document.", 'kyc_status': KycStatus.PENDING},
            status=status.HTTP_200_OK,
        )
