import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction

from apps.core.choices import BookingStatus, KycStatus, NotificationType, TripDocumentType
from apps.core.models import AppSetting
from apps.notifications.services import notify
from utils.order_reference import confirmation_code
from .models import Booking, TripDocument

logger = logging.getLogger(__name__)


def _unique_code() -> str:
    for _ in range(10):
        code = confirmation_code()
        if not Booking.objects.filter(confirmation_code=code).exists():
            return code
    raise RuntimeError("Could not generate a unique confirmation code")


def create_booking(goal) -> Booking:
    """§7.10: one confirmed booking per completed goal, with trip documents."""
    existing = Booking.objects.filter(goal=goal).first()
    if existing:
        return existing

    itinerary = goal.itinerary
    operator = itinerary.operator
    traveller_count = goal.travellers.count()

    for _ in range(3):
        try:
            with transaction.atomic():
                booking = Booking.objects.create(
                    goal=goal, confirmation_code=_unique_code(), status=BookingStatus.CONFIRMED,
                    travel_date=goal.travel_date,
                )
            break
        except IntegrityError:
            existing = Booking.objects.filter(goal=goal).first()
            if existing:
                return existing
    else:
        raise RuntimeError("Could not create booking")

    code = booking.confirmation_code
    contacts = [operator.name]
    if operator.phone_number:
        contacts.append(f"Phone: {operator.phone_number}")
    if operator.whatsapp:
        contacts.append(f"WhatsApp: {operator.whatsapp}")
    if operator.email:
        contacts.append(f"Email: {operator.email}")

    TripDocument.objects.bulk_create([
        TripDocument(
            booking=booking, type=TripDocumentType.VOUCHER, title="Safari voucher", position=0,
            content=(
                f"Confirmation: {code}\nTrip: {itinerary.title}\nTravel date: {goal.travel_date.isoformat()}\n"
                f"Travellers: {traveller_count}\nOperator: {operator.name}\n\n"
                "Present this voucher to your guide on day 1."
            ),
        ),
        TripDocument(booking=booking, type=TripDocumentType.OPERATOR_CONTACTS, title="Operator contacts",
                     position=1, content="\n".join(contacts)),
        TripDocument(booking=booking, type=TripDocumentType.PACKING_LIST, title="Packing list", position=2,
                     content=AppSetting.get().packing_list),
    ])

    user = goal.user
    if itinerary.kyc_required and user.kyc_status != KycStatus.VERIFIED:
        type(user).objects.filter(pk=user.pk).update(kyc_status=KycStatus.PENDING)

    notify(user, "Trip confirmed! 🎉",
           f"{goal.title} is fully paid. Your booking {code} and trip documents are ready.",
           NotificationType.GOAL_COMPLETED, goal)

    if settings.EMAIL_OPERATOR_ON_BOOKING and operator.email:
        transaction.on_commit(lambda: _email_operator(booking.pk))
    return booking


def _email_operator(booking_id: int) -> None:
    booking = Booking.objects.select_related('goal__itinerary__operator', 'goal__user').get(pk=booking_id)
    goal = booking.goal
    travellers = "\n".join(
        f"- {t.name} ({t.get_age_category_display()}, {t.get_residency_display()})" for t in goal.travellers.all()
    )
    try:
        send_mail(
            subject=f"New SafariChap booking {booking.confirmation_code}",
            message=(
                f"Booking: {booking.confirmation_code}\nTrip: {goal.itinerary.title}\n"
                f"Travel date: {booking.travel_date.isoformat()}\n"
                f"Lead traveller: {goal.user.full_name or '-'} {goal.user.phone_number or ''}\n\n"
                f"Travellers:\n{travellers}\n"
            ),
            from_email=None,
            recipient_list=[goal.itinerary.operator.email],
        )
    except Exception:
        logger.exception("Operator email failed for booking %s", booking.confirmation_code)
