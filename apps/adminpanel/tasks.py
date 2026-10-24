import logging

from celery import shared_task

from apps.core.choices import NotificationType
from apps.notifications.services import notify
from apps.userauth.models import UserAccount
from .models import Broadcast

logger = logging.getLogger(__name__)


@shared_task
def send_broadcast(broadcast_id: int, user_ids: list[int]):
    """One Notification row + push per recipient."""
    broadcast = Broadcast.objects.get(pk=broadcast_id)
    sent = 0
    for user in UserAccount.objects.filter(pk__in=user_ids).iterator():
        try:
            notify(user, broadcast.title, broadcast.message, NotificationType.ANNOUNCEMENT)
            sent += 1
        except Exception:
            logger.exception("Broadcast %s failed for user %s", broadcast_id, user.pk)
    return {'sent': sent}
