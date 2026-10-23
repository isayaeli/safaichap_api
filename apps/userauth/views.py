from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.choices import KycStatus
from .models import DeviceToken, KycDocument, UserAccount
from .serializers import DeviceTokenSerializer, KycSubmitSerializer, UserSerializer


class CurrentUserAPIView(APIView):
    """GET/PATCH /api/users/me/ — the profile is created on first authenticated call."""
    throttle_scope = 'account'

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RegisterDeviceView(APIView):
    """POST /api/users/devices/ — upsert on token and reassign it to the current user."""
    throttle_scope = 'account'

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
