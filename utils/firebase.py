import json
import logging
import os

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings

logger = logging.getLogger(__name__)

_INVALID_TOKEN_MARKERS = ('requested entity was not found', 'unregistered', 'invalid registration', 'not a valid fcm')


def initialize_firebase():
    """Initialises the default firebase_admin app once, from env-provided credentials."""
    if firebase_admin._apps:
        return firebase_admin.get_app()

    try:
        if settings.FIREBASE_CREDENTIALS_JSON:
            cred = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
        elif settings.FIREBASE_CREDENTIALS_PATH and os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        else:
            logger.warning("Firebase credentials not configured; auth and push are disabled.")
            return None
    except (ValueError, OSError) as e:
        # e.g. the placeholder in secrets/ hasn't been replaced yet. Don't crash startup.
        logger.warning("Firebase credentials are invalid (%s); auth and push are disabled.", type(e).__name__)
        return None
    return firebase_admin.initialize_app(cred)


def send_push_notification(user, title, body, data=None, is_reminder=False):
    """
    Sends an FCM push to every enabled device of `user` and removes tokens FCM
    reports as invalid. Reminder pushes respect `user.notifications_enabled`;
    payment results are always sent.
    """
    from apps.userauth.models import DeviceToken

    if is_reminder and not user.notifications_enabled:
        return False
    if not firebase_admin._apps:
        logger.debug("Firebase not initialised; skipping push to user %s", user.pk)
        return False

    tokens = list(
        DeviceToken.objects.filter(user=user, notifications_enabled=True)
        .exclude(token__isnull=True).exclude(token__exact='')
        .values_list('token', flat=True)
    )
    if not tokens:
        logger.debug("No valid tokens for user %s", user.pk)
        return False

    payload = {k: '' if v is None else str(v) for k, v in (data or {}).items()}
    sent = False
    for token in tokens:
        try:
            # The app (firebase_messaging 17+) registers its Firebase installation
            # ID, which FCM targets via `fid`, not the legacy registration `token`.
            messaging.send(messaging.Message(
                fid=token,
                notification=messaging.Notification(title=title, body=body),
                data=payload,
            ))
            sent = True
        except Exception as e:
            error_str = str(e).lower()
            logger.warning("Failed to send push to user %s: %s", user.pk, type(e).__name__)
            if isinstance(e, messaging.UnregisteredError) or any(m in error_str for m in _INVALID_TOKEN_MARKERS):
                DeviceToken.objects.filter(token=token, user=user).delete()
    return sent
