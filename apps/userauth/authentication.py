import logging
from datetime import timedelta

from django.utils import timezone
from firebase_admin import auth
from rest_framework import authentication
from rest_framework import exceptions

from .models import UserAccount

logger = logging.getLogger(__name__)


class FirebaseAuthentication(authentication.BaseAuthentication):
    """
    `Authorization: Bearer <Firebase ID token>`. Invalid or expired tokens get a
    401 (the app refreshes its token and retries once), so never use 401 for
    business errors.
    """
    keyword = 'Bearer'

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise exceptions.AuthenticationFailed("Invalid authorization header.")
        id_token = parts[1]

        try:
            decoded_token = auth.verify_id_token(id_token)
        except Exception as e:
            # Never log the token itself or echo provider errors to clients.
            logger.info("Firebase token rejected: %s", type(e).__name__)
            raise exceptions.AuthenticationFailed("Your session has expired. Please sign in again.")

        firebase_uid = decoded_token.get("uid")
        if not firebase_uid:
            raise exceptions.AuthenticationFailed("Your session has expired. Please sign in again.")

        user, created = UserAccount.objects.get_or_create(
            username=firebase_uid,
            defaults={
                'email': decoded_token.get('email') or None,
                'phone_number': decoded_token.get('phone_number') or None,
                'is_active': True,
            }
        )
        if not user.is_active:
            raise exceptions.AuthenticationFailed("This account is disabled.")

        if not user.last_login or user.last_login < timezone.now() - timedelta(minutes=5):
            UserAccount.objects.filter(pk=user.pk).update(last_login=timezone.now())

        return (user, None)

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) for missing/invalid credentials.
        return self.keyword
