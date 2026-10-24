import logging

from celery import shared_task

from apps.core.choices import NotificationType
from apps.notifications.models import Notification
from apps.userauth.models import UserAccount
from utils.firebase import send_push_notification
from .models import Broadcast

logger = logging.getLogger(__name__)


@shared_task
def send_broadcast(broadcast_id: int, user_ids: list[int]):
    """
    One Notification row + push per recipient, then stores the delivery totals
    on the Broadcast. Pushes are sent directly (not via notify()) so we know
    which ones reached a device.
    """
    broadcast = Broadcast.objects.get(pk=broadcast_id)
    sent = pushed = failed = 0
    for user in UserAccount.objects.filter(pk__in=user_ids).iterator():
        try:
            Notification.objects.create(user=user, title=broadcast.title, message=broadcast.message,
                                        type=NotificationType.ANNOUNCEMENT)
            sent += 1
        except Exception:
            logger.exception("Broadcast %s failed for user %s", broadcast_id, user.pk)
            failed += 1
            continue
        try:
            if send_push_notification(user, broadcast.title, broadcast.message,
                                      data={'goal_uuid': '', 'type': str(NotificationType.ANNOUNCEMENT)}):
                pushed += 1
        except Exception:
            logger.exception("Broadcast %s push failed for user %s", broadcast_id, user.pk)
    Broadcast.objects.filter(pk=broadcast_id).update(sent=sent, pushed=pushed, failed=failed)
    return {'sent': sent, 'pushed': pushed, 'failed': failed}
