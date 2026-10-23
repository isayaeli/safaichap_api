import logging
from datetime import timedelta

from celery import shared_task

from apps.core.choices import GoalStatus, NotificationType
from apps.core.models import AppSetting
from apps.notifications.services import notify
from utils.dates import today as local_today
from utils.money import format_major
from .models import Installment, SavingsGoal
from .services.goals import ACCEPTS_PAYMENTS, process_goal_schedule
from .services.schedule import OPEN_STATUSES

logger = logging.getLogger(__name__)


@shared_task
def process_missed_and_expired():
    """Daily 00:15 EAT: missed installments, pause after N misses, expiry after pay-by."""
    today = local_today()
    ids = list(SavingsGoal.objects.filter(status__in=ACCEPTS_PAYMENTS).values_list('id', flat=True))
    for goal_id in ids:
        try:
            process_goal_schedule(goal_id, today)
        except Exception:
            logger.exception("Schedule processing failed for goal %s", goal_id)
    return {"goals": len(ids)}


@shared_task
def send_due_reminders():
    """Daily 09:00 EAT: `installment_due` N days before and on the due day."""
    today = local_today()
    ahead = today + timedelta(days=AppSetting.get().reminder_days_before_due)
    installments = (
        Installment.objects.filter(
            due_date__in=[today, ahead], status__in=OPEN_STATUSES, goal__status__in=ACCEPTS_PAYMENTS,
        ).select_related('goal__user')
    )
    sent = 0
    for inst in installments:
        goal = inst.goal
        outstanding = format_major(inst.amount - inst.amount_paid, goal.currency)
        if inst.due_date == today:
            title, message = "Installment due today", f"{outstanding} for {goal.title} is due today."
        else:
            title = "Installment due soon"
            message = f"{outstanding} for {goal.title} is due on {inst.due_date.strftime('%d %b %Y')}."
        notify(goal.user, title, message, NotificationType.INSTALLMENT_DUE, goal)
        sent += 1
    return {"sent": sent}
