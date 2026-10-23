"""
Load-testing data: hundreds of generated trips plus, for each chosen user, a
history of goals (every status), installments, payments, bookings,
notifications and wishlist items. Everything it creates is tagged so
`--clear` removes it again: itinerary slugs start with `bulk-`, operator
emails end with BULK_EMAIL_DOMAIN, and user data only references bulk trips.
No pushes are sent; rows are written directly.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from apps.bookings.models import Booking, TripDocument
from apps.catalogue import seed_data
from apps.catalogue.models import (
    Destination, Itinerary, ItineraryDay, ItineraryDestination, ItineraryPricing, Operator, RefundPolicy, SeasonalAdjustment,
)
from apps.core.choices import (
    AccommodationLevel, AgeCategory, BookingStatus, GoalStatus, InstallmentStatus, NotificationType,
    PaymentFrequency, PaymentMethod, PaymentStatus, Residency, TripDocumentType,
)
from apps.core.models import AppSetting
from apps.goals.models import SavingsGoal
from apps.goals.services import schedule as schedule_rules
from apps.goals.services.goals import build_plan, create_goal, write_schedule
from apps.notifications.models import Notification
from apps.payments.models import Payment, Refund
from apps.userauth.models import UserAccount
from utils.exceptions import BadRequest
from utils.money import format_major
from utils.order_reference import confirmation_code, generate_order_reference, receipt_number

BULK_SLUG_PREFIX = 'bulk-'
BULK_EMAIL_DOMAIN = 'bulk.safarichap.test'

EXTRA_DESTINATIONS = [
    ("Arusha National Park", "Northern circuit"), ("Mount Meru", "Northern circuit"),
    ("Lake Natron", "Northern circuit"), ("Lake Eyasi", "Northern circuit"),
    ("Mkomazi", "Northern circuit"), ("Usambara Mountains", "Northern circuit"),
    ("Katavi", "Western circuit"), ("Gombe Stream", "Western circuit"), ("Mahale Mountains", "Western circuit"),
    ("Rubondo Island", "Western circuit"), ("Udzungwa Mountains", "Southern circuit"),
    ("Kitulo Plateau", "Southern circuit"), ("Saadani", "Coast"), ("Pemba", "Coast"),
    ("Mafia Island", "Coast"), ("Kilwa Kisiwani", "Coast"), ("Bagamoyo", "Coast"),
]
OPERATOR_WORDS = (["Simba", "Twiga", "Tembo", "Nyati", "Duma", "Chui", "Kifaru", "Pundamilia", "Baobab",
                   "Acacia", "Kopje", "Rift", "Horizon", "Sundowner", "Migration", "Bushbuck"],
                  ["Safaris", "Expeditions", "Adventures", "Tours", "Journeys", "Trails", "Travel Co."])
TRIP_STYLES = ["Classic", "Explorer", "Family", "Photographic", "Honeymoon", "Budget Camping", "Walking",
               "Fly-in", "Highlights", "Off the Beaten Track", "Wildlife & Beach", "Great Migration"]
DAY_ACTIVITIES = ["Morning game drive", "Full day game drive", "Guided bush walk", "Boat safari",
                  "Village & cultural visit", "Sundowner and night drive", "Crater descent",
                  "Beach & snorkelling", "Spice farm tour", "Hike to the viewpoint", "Picnic lunch in the bush"]
CAMPS = ["Tented Camp", "Safari Lodge", "Bush Camp", "Eco Lodge", "Public Campsite", "Beach Resort"]
INCLUSIONS = ["Park & conservation fees", "Professional driver-guide", "4x4 Land Cruiser with pop-up roof",
              "Full board accommodation", "Bottled water on game drives", "Airport transfers",
              "Domestic flights", "Flying Doctors evacuation cover", "Binoculars on board"]
EXCLUSIONS = ["International flights", "Visa", "Tips", "Travel insurance", "Alcoholic drinks",
              "Optional balloon safari", "Personal items"]
TRAVELLER_NAMES = ["Asha", "Baraka", "Neema", "Juma", "Rehema", "Daudi", "Zawadi", "Emmanuel", "Upendo",
                   "Hamisi", "Grace", "Salim", "Mwajuma", "Peter", "Faraja", "Tumaini"]
SURNAMES = ["Mushi", "Mollel", "Kimaro", "Massawe", "Mrema", "Swai", "Lyimo", "Mwakyusa", "Shayo", "Temba"]

# Weighted share of each goal status in a user's history.
STATUS_WEIGHTS = {
    GoalStatus.ACTIVE: 40, GoalStatus.COMPLETED: 15, GoalStatus.DRAFT: 15, GoalStatus.PAUSED: 10,
    GoalStatus.CANCELLED: 12, GoalStatus.EXPIRED: 8,
}
MOBILE_METHODS = [PaymentMethod.MPESA, PaymentMethod.AIRTEL_MONEY, PaymentMethod.MIXX_BY_YAS,
                  PaymentMethod.HALO_PESA]


def _img(seed):
    return f"https://picsum.photos/seed/{seed}/900/600"


class Command(BaseCommand):
    help = "Seeds lots of fake catalogue and user data to see how the app behaves at volume."

    def add_arguments(self, parser):
        parser.add_argument('--itineraries', type=int, default=300, help="Bulk trips to generate (default 300).")
        parser.add_argument('--operators', type=int, default=20, help="Bulk operators (default 20).")
        parser.add_argument('--goals', type=int, default=60, help="Goals per user (default 60).")
        parser.add_argument('--wishlist', type=int, default=80, help="Wishlist items per user (default 80).")
        parser.add_argument('--user', action='append', default=[],
                            help="Username (Firebase uid) or email to seed; repeatable. "
                                 "Default: every non-staff user that has an email.")
        parser.add_argument('--catalogue-only', action='store_true', help="Skip per-user data.")
        parser.add_argument('--clear', action='store_true', help="Delete previously seeded bulk data and exit.")
        parser.add_argument('--seed', type=int, default=42, help="Random seed, for repeatable data.")

    def handle(self, *args, **options):
        self.rng = random.Random(options['seed'])
        if options['clear']:
            self.clear()
            return

        with transaction.atomic():
            # The goal planner needs FX rates and the base catalogue settings.
            AppSetting.get()
            from django.core.management import call_command
            call_command('seed_catalogue', stdout=self.stdout)

            self.clear(quiet=True)
            itineraries = self.seed_catalogue(options['itineraries'], options['operators'])

        if options['catalogue_only']:
            return

        users = self.pick_users(options['user'])
        if not users:
            self.stdout.write(self.style.WARNING(
                "No users to seed. Sign in to the app once, or pass --user <uid or email>."))
            return
        for user in users:
            with transaction.atomic():
                counts = self.seed_user(user, itineraries, options['goals'], options['wishlist'])
            self.stdout.write(self.style.SUCCESS(
                f"{user.email or user.username}: " + ", ".join(f"{v} {k}" for k, v in counts.items())))

    # ── Clearing ────────────────────────────────────────────────────────

    @transaction.atomic
    def clear(self, quiet=False):
        bulk_trips = Itinerary.objects.filter(slug__startswith=BULK_SLUG_PREFIX)
        goals = SavingsGoal.objects.filter(itinerary__in=bulk_trips)
        Notification.objects.filter(goal__in=goals).delete()
        Payment.objects.filter(goal__in=goals).delete()
        Refund.objects.filter(goal__in=goals).delete()
        Booking.objects.filter(goal__in=goals).delete()
        goal_count, _ = goals.delete()
        trip_count = bulk_trips.count()
        bulk_trips.delete()
        Operator.objects.filter(email__endswith='@' + BULK_EMAIL_DOMAIN).delete()
        if not quiet:
            self.stdout.write(self.style.SUCCESS(f"Removed {trip_count} bulk trips and their goals/payments."))

    # ── Catalogue ───────────────────────────────────────────────────────

    def seed_catalogue(self, count, operator_count):
        rng = self.rng
        policy = RefundPolicy.objects.filter(is_default=True).first()

        for name, region in EXTRA_DESTINATIONS:
            Destination.objects.update_or_create(name=name, defaults={'region': region, 'image': _img(slugify(name))})
        destinations = list(Destination.objects.all())
        by_region = {}
        for d in destinations:
            by_region.setdefault(d.region, []).append(d)

        operators = []
        used = set()
        while len(operators) < operator_count:
            name = f"{rng.choice(OPERATOR_WORDS[0])} {rng.choice(OPERATOR_WORDS[1])}"
            if name in used:
                if len(used) >= len(OPERATOR_WORDS[0]) * len(OPERATOR_WORDS[1]):
                    break
                continue
            used.add(name)
            operators.append(Operator.objects.create(
                name=name, lead_time_days=rng.choice([7, 10, 14, 21, 30]),
                phone_number=f"+2557{rng.randint(10000000, 99999999)}",
                whatsapp=f"+2557{rng.randint(10000000, 99999999)}",
                email=f"{slugify(name)}@{BULK_EMAIL_DOMAIN}", refund_policy=policy,
            ))

        itineraries, links, days, pricings = [], [], [], []
        for i in range(count):
            region = rng.choice(list(by_region))
            pool = by_region[region]
            picked = rng.sample(pool, k=min(len(pool), rng.randint(1, 4)))
            if rng.random() < 0.2 and region != 'Coast' and 'Coast' in by_region:
                picked.append(rng.choice(by_region['Coast']))
            duration = rng.randint(max(1, len(picked)), 14)
            level = rng.choice(AccommodationLevel.values)
            style = rng.choice(TRIP_STYLES)
            title = f"{duration}-Day {' & '.join(d.name for d in picked[:3])} {style}"
            min_group = rng.choice([1, 1, 1, 2])
            itineraries.append(Itinerary(
                title=title, slug=f"{BULK_SLUG_PREFIX}{i:04d}-{slugify(title)}"[:200],
                summary=f"{style} {level.replace('_', '-')} trip through {', '.join(d.name for d in picked)}, "
                        f"{duration} day{'s' if duration > 1 else ''} with {rng.choice(CAMPS).lower()} stays.",
                duration_days=duration, accommodation_level=level,
                inclusions=rng.sample(INCLUSIONS, k=rng.randint(3, 7)),
                exclusions=rng.sample(EXCLUSIONS, k=rng.randint(2, 5)),
                images=[_img(f"bulk-{i}-{n}") for n in range(rng.randint(1, 5))],
                operator=rng.choice(operators), lead_time_days=rng.choice([None, None, 7, 14, 30]),
                min_group_size=min_group, max_group_size=rng.randint(max(min_group, 4), 12),
                is_active=rng.random() > 0.05, is_featured=rng.random() < 0.05, sort_order=1000 + i,
                kyc_required=rng.random() < 0.1,
            ))
            itineraries[-1]._picked = picked
        Itinerary.objects.bulk_create(itineraries)

        for it in itineraries:
            for pos, d in enumerate(it._picked):
                links.append(ItineraryDestination(itinerary=it, destination=d, position=pos))
            for n in range(1, it.duration_days + 1):
                place = it._picked[min(len(it._picked) - 1, (n - 1) * len(it._picked) // it.duration_days)]
                days.append(ItineraryDay(
                    itinerary=it, day_number=n, title=f"{rng.choice(DAY_ACTIVITIES)} in {place.name}",
                    location=place.name, description=f"Day {n} of the {it.title.lower()}.",
                    meals=["breakfast", "lunch", "dinner"] if n < it.duration_days else ["breakfast"],
                    accommodation=f"{place.name} {rng.choice(CAMPS)}" if n < it.duration_days else "—",
                ))
            factor = {'budget': 1, 'mid_range': 2, 'luxury': 4}[it.accommodation_level] * it.duration_days
            if rng.random() < 0.25:
                adult = rng.randint(80, 200) * 1000 * factor  # TZS, no minor unit
                currency = 'TZS'
            else:
                adult = rng.randint(80, 220) * 100 * factor  # USD cents
                currency = 'USD'
            pricings.append(ItineraryPricing(
                itinerary=it, base_currency=currency, resident_adult=adult, resident_child=adult * 55 // 100,
                non_resident_adult=adult * rng.randint(220, 300) // 100,
                non_resident_child=adult * rng.randint(120, 170) // 100,
            ))
        ItineraryDestination.objects.bulk_create(links)
        ItineraryDay.objects.bulk_create(days, batch_size=2000)
        ItineraryPricing.objects.bulk_create(pricings)
        SeasonalAdjustment.objects.bulk_create([
            SeasonalAdjustment(pricing=p, **season)
            for p in pricings if rng.random() < 0.6 for season in seed_data.high_seasons()
        ])

        self.stdout.write(self.style.SUCCESS(
            f"Bulk catalogue: {len(operators)} operators, {len(destinations)} destinations, "
            f"{len(itineraries)} trips, {len(days)} itinerary days."))
        return [it for it in itineraries if it.is_active]

    # ── Per-user data ───────────────────────────────────────────────────

    def pick_users(self, identifiers):
        if not identifiers:
            return list(UserAccount.objects.filter(is_staff=False).exclude(Q(email__isnull=True) | Q(email='')))
        users = []
        for ident in identifiers:
            matched = list(UserAccount.objects.filter(Q(username=ident) | Q(email__iexact=ident)))
            if not matched:
                raise CommandError(f"No user with username or email '{ident}'.")
            users += matched
        return users

    def seed_user(self, user, itineraries, goal_count, wishlist_count):
        from apps.wishlist.models import WishlistItem

        rng = self.rng
        today = timezone.localdate()
        counts = dict.fromkeys(['goals', 'installments', 'payments', 'bookings', 'notifications', 'wishlist'], 0)

        picks = rng.sample(itineraries, k=min(wishlist_count, len(itineraries)))
        WishlistItem.objects.bulk_create([WishlistItem(user=user, itinerary=it) for it in picks],
                                         ignore_conflicts=True)
        counts['wishlist'] = len(picks)

        statuses, weights = zip(*STATUS_WEIGHTS.items())
        attempts = 0
        while counts['goals'] < goal_count and attempts < goal_count * 5:
            attempts += 1
            status = rng.choices(statuses, weights)[0]
            goal = self.make_goal(user, rng.choice(itineraries), status, today, counts)
            if goal:
                counts['goals'] += 1
        return counts

    def make_goal(self, user, itinerary, status, today, counts):
        rng = self.rng
        started = today - timedelta(days=rng.randint(0, 5) if status == GoalStatus.DRAFT else rng.randint(20, 300))
        travel_date = started + timedelta(days=rng.randint(90, 420))
        if status == GoalStatus.COMPLETED and rng.random() < 0.5:
            travel_date = today - timedelta(days=rng.randint(1, 60))  # a trip already taken
            started = travel_date - timedelta(days=rng.randint(120, 300))
        if status == GoalStatus.EXPIRED:
            travel_date = today + timedelta(days=rng.randint(0, 20))

        size = rng.randint(itinerary.min_group_size, min(itinerary.max_group_size, 5))
        residency = user.residency or Residency.RESIDENT
        travellers = [{
            'name': f"{rng.choice(TRAVELLER_NAMES)} {rng.choice(SURNAMES)}",
            'age_category': AgeCategory.ADULT if n == 0 or rng.random() < 0.6 else AgeCategory.CHILD,
            'residency': residency,
        } for n in range(size)]
        if (user.full_name or '').strip():
            travellers[0]['name'] = user.full_name
        currency = rng.choice(['TZS', 'TZS', 'USD', user.preferred_currency or 'TZS', 'EUR', 'GBP'])
        frequency = rng.choice(PaymentFrequency.values)
        custom_days = rng.choice([10, 20, 45]) if frequency == PaymentFrequency.CUSTOM else 30

        try:
            plan = build_plan(itinerary, travellers, travel_date, currency, frequency, custom_days, today=started)
        except BadRequest:
            return None
        if rng.random() < 0.4:
            plan.deposit = plan.breakdown.total * rng.choice([10, 20, 30]) // 100
            plan.schedule = schedule_rules.generate(
                total=plan.breakdown.total, deposit=plan.deposit, today=started, pay_by_date=plan.pay_by_date,
                frequency=frequency, custom_days=custom_days,
                minimum_payment=AppSetting.get().minimum_payment(currency),
            )

        goal = create_goal(user, plan, title=self.goal_title(itinerary))
        started_at = timezone.make_aware(timezone.datetime.combine(started, timezone.datetime.min.time())) \
            + timedelta(hours=rng.randint(7, 21), minutes=rng.randint(0, 59))
        SavingsGoal.objects.filter(pk=goal.pk).update(created_at=started_at)
        if status == GoalStatus.DRAFT:
            return goal

        goal.locked_fx_numerator, goal.locked_fx_denominator = plan.fx
        goal.locked_pricing_snapshot = plan.pricing_snapshot
        goal.activated_at = started_at
        entries = plan.schedule
        write_schedule(goal, entries)

        # Pay what fell due before today; some goals fall behind, completed ones pay everything.
        notifications = []
        missed = 0
        for e in sorted(entries, key=lambda e: e.due_date):
            due_passed = e.due_date <= today
            if status == GoalStatus.COMPLETED:
                pay = True
            elif not due_passed:
                pay = rng.random() < 0.08  # occasional early payment
            elif status in (GoalStatus.PAUSED, GoalStatus.EXPIRED) and rng.random() < 0.6:
                pay = False
            else:
                pay = rng.random() < 0.9
            paid_on = min(e.due_date, today) - timedelta(days=rng.randint(0, 3))
            if pay:
                amount = e.amount - e.amount_paid
                if rng.random() < 0.1 and status != GoalStatus.COMPLETED:
                    amount = amount // 2 or amount  # partial payment
                e.amount_paid += amount
                e.status = InstallmentStatus.PAID if e.amount_paid >= e.amount else InstallmentStatus.PARTIALLY_PAID
                self.make_payment(goal, amount, paid_on, PaymentStatus.SUCCESS, counts)
                notifications.append((paid_on, "Payment received",
                                      f"{format_major(amount, goal.currency)} added to {goal.title}.",
                                      NotificationType.PAYMENT_SUCCESS))
                if rng.random() < 0.1:
                    self.make_payment(goal, amount, paid_on - timedelta(hours=2), PaymentStatus.FAILED, counts)
                    notifications.append((paid_on, "Payment failed",
                                          "Your payment didn't go through. Please try again.",
                                          NotificationType.PAYMENT_FAILED))
            elif due_passed:
                e.status = InstallmentStatus.MISSED
                missed += 1
                notifications.append((e.due_date + timedelta(days=1), "Installment missed",
                                      f"You missed the {format_major(e.amount, goal.currency)} payment for "
                                      f"{goal.title}.", NotificationType.INSTALLMENT_MISSED))
            if e.due_date - timedelta(days=3) <= today and rng.random() < 0.7:
                notifications.append((e.due_date - timedelta(days=3), "Payment due soon",
                                      f"{format_major(e.amount, goal.currency)} for {goal.title} is due on "
                                      f"{e.due_date:%d %b}.", NotificationType.INSTALLMENT_DUE))
        write_schedule(goal, entries)
        counts['installments'] += len(entries)

        goal.amount_paid = sum(e.amount_paid for e in entries)
        goal.status = status
        goal.consecutive_missed = missed if status == GoalStatus.PAUSED else 0
        if status == GoalStatus.CANCELLED:
            goal.cancellation_reason = rng.choice([None, "Change of plans", "Found a different trip",
                                                   "Dates no longer work"])
            notifications.append((today - timedelta(days=rng.randint(0, 10)), "Goal cancelled",
                                  f"{goal.title} has been cancelled.", NotificationType.GOAL_CANCELLED))
        elif status == GoalStatus.PAUSED:
            notifications.append((today - timedelta(days=rng.randint(0, 10)), "Goal paused",
                                  f"{goal.title} is paused after missed payments. Pay any amount to resume.",
                                  NotificationType.GOAL_PAUSED))
        elif status == GoalStatus.EXPIRED:
            notifications.append((goal.pay_by_date, "Goal expired",
                                  f"The pay-by date for {goal.title} has passed. Reschedule to keep going.",
                                  NotificationType.GOAL_EXPIRED))
        elif status == GoalStatus.COMPLETED:
            goal.completed_at = timezone.now() - timedelta(days=rng.randint(0, 30))
            code = self.make_booking(goal, today)
            counts['bookings'] += 1
            notifications.append((goal.completed_at.date(), "Trip confirmed! 🎉",
                                  f"{goal.title} is fully paid. Your booking {code} and trip documents are ready.",
                                  NotificationType.GOAL_COMPLETED))
        goal.save()

        rows = Notification.objects.bulk_create([
            Notification(user=user, goal=goal, title=t, message=m, type=kind, is_read=d < today - timedelta(days=7)
                         or rng.random() < 0.3)
            for d, t, m, kind in notifications if d <= today
        ])
        for row, (d, *_rest) in zip(rows, [n for n in notifications if n[0] <= today]):
            Notification.objects.filter(pk=row.pk).update(
                created_at=timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.min.time()))
                + timedelta(hours=rng.randint(8, 20), minutes=rng.randint(0, 59)))
        counts['notifications'] += len(rows)
        return goal

    def goal_title(self, itinerary):
        return self.rng.choice([
            None, None, f"{self.rng.choice(['Birthday', 'Anniversary', 'Family', 'Easter', 'December'])} safari",
            f"{itinerary.destination_links.first().destination.name} {self.rng.choice(['trip', 'getaway', 'dream'])}",
        ])

    def make_payment(self, goal, amount, paid_on, status, counts):
        rng = self.rng
        mobile = goal.currency == 'TZS'
        when = timezone.make_aware(timezone.datetime.combine(paid_on, timezone.datetime.min.time())) \
            + timedelta(hours=rng.randint(7, 22), minutes=rng.randint(0, 59))
        payment = Payment.objects.create(
            goal=goal, user=goal.user, amount=amount, currency=goal.currency,
            method=rng.choice(MOBILE_METHODS) if mobile else PaymentMethod.CARD,
            phone_number=f"2557{rng.randint(10000000, 99999999)}" if mobile else None,
            order_reference=generate_order_reference(), provider='clickpesa' if mobile else 'flutterwave',
            provider_reference=f"SEED{rng.randint(10 ** 9, 10 ** 10 - 1)}", status=status,
            failure_reason="Insufficient balance" if status == PaymentStatus.FAILED else None,
            receipt_number=receipt_number() if status == PaymentStatus.SUCCESS else None,
            settled_at=when,
        )
        Payment.objects.filter(pk=payment.pk).update(created_at=when)
        counts['payments'] += 1

    def make_booking(self, goal, today):
        code = confirmation_code()
        while Booking.objects.filter(confirmation_code=code).exists():
            code = confirmation_code()
        booking = Booking.objects.create(
            goal=goal, confirmation_code=code, travel_date=goal.travel_date,
            status=BookingStatus.COMPLETED if goal.travel_date < today else BookingStatus.CONFIRMED,
        )
        operator = goal.itinerary.operator
        TripDocument.objects.bulk_create([
            TripDocument(booking=booking, type=TripDocumentType.VOUCHER, title="Safari voucher", position=0,
                         content=f"Confirmation: {code}\nTrip: {goal.itinerary.title}\n"
                                 f"Travel date: {goal.travel_date.isoformat()}\nOperator: {operator.name}"),
            TripDocument(booking=booking, type=TripDocumentType.OPERATOR_CONTACTS, title="Operator contacts",
                         position=1, content=f"{operator.name}\nPhone: {operator.phone_number}\n"
                                             f"Email: {operator.email}"),
            TripDocument(booking=booking, type=TripDocumentType.PACKING_LIST, title="Packing list", position=2,
                         content=AppSetting.get().packing_list),
        ])
        return code
