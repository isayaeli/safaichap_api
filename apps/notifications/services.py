import logging

from django.db import transaction

from apps.core.choices import NotificationType
from utils.firebase import send_push_notification
from .models import Notification

logger = logging.getLogger(__name__)

REMINDER_TYPES = {NotificationType.INSTALLMENT_DUE}


def notify(user, title: str, message: str, type: str, goal=None) -> Notification:
    """
    Writes the in-app Notification row (the app's list reads it) and sends the
    FCM push once the surrounding transaction commits. Reminder pushes respect
    user.notifications_enabled; everything else (payment results etc.) is always sent.
    """
    notification = Notification.objects.create(user=user, goal=goal, title=title, message=message, type=type)
    data = {'goal_uuid': str(goal.uuid) if goal else '', 'type': str(type)}

    def _push():
        try:
            send_push_notification(user, title, message, data=data, is_reminder=type in REMINDER_TYPES)
        except Exception:
            logger.exception("Push failed for notification %s", notification.uuid)

    transaction.on_commit(_push)
    return notification
