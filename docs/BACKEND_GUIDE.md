# SafariChap API — Backend Build Guide

Instructions for building the Django backend (`safarichap_api`) that the SafariChap Flutter
app already talks to. Everything here comes from the app as it stands (services, models and
the in-app mock backend), so if you follow it the app works when you run it with
`--dart-define=USE_MOCK_API=false`.

> **Source of truth in the app repo**
> - Endpoints: `lib/src/data/services/**/*_service.dart`
> - JSON shapes: `lib/src/data/models/**` (field names are the JSON keys)
> - Reference behaviour: `lib/src/data/mock/mock_backend.dart` (a working emulation of every rule below)
> - Rules: `lib/src/core/utils/pricing_calculator.dart`, `schedule_calculator.dart`, `core/money/*`
> - Seed catalogue: `lib/src/data/mock/mock_seed.dart`
>
> If this document and the app disagree, the app wins. Update this doc.

---

## 1. Stack & project layout

Mirror `isayaeli/salonchap_api`: same stack, same layout, same Firebase auth class.

- Python 3.12, **Django 5.2**, **Django REST Framework 3.16**, PostgreSQL 16
- **Celery 5 + django-celery-beat**, Redis (broker, cache, locks)
- `firebase_admin` for verifying ID tokens and sending FCM pushes
- `django-filter`, `drf-yasg` (Swagger at `/swagger/`), `django-prometheus`
- Docker Compose (`docker-compose.dev.yaml`, `docker-compose.yaml`) with nginx

```
safarichap_api/
  config/
    settings/{base,development,production}.py
    celery.py  urls.py  asgi.py  wsgi.py
  apps/
    userauth/        # UserAccount, DeviceToken, KycDocument, FirebaseAuthentication
    catalogue/       # Operator, Itinerary, ItineraryDay, ItineraryPricing, SeasonalAdjustment, Destination
    goals/           # SavingsGoal, Traveller, Installment  + services/pricing.py, services/schedule.py
    payments/        # Payment, provider clients, webhooks, tasks
    bookings/        # Booking, TripDocument
    notifications/   # Notification + push helpers
    wishlist/        # WishlistItem
    core/            # FxRate, AppSetting (configurable rules), money helpers
  utils/
    firebase.py  clickpesa.py  card_gateway.py  order_reference.py  pagination_util.py  money.py
  docker/  requirements/  manage.py
```

All routes live under `/api/` and **end with a trailing slash** (the app calls e.g.
`/api/goals/quote/`).

---

## 2. Conventions the app depends on

### 2.1 Auth

- Every request carries `Authorization: Bearer <Firebase ID token>`.
- Reuse salonchap's `FirebaseAuthentication`: verify with `firebase_admin.auth.verify_id_token`, then `get_or_create` a `UserAccount` with `username=<firebase uid>`. Copy `phone_number` and `email` from the decoded token on create.
- On an invalid or expired token, return **401**. The app force-refreshes the token and retries **once**, so don't return 401 for business errors.
- Set `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`. Webhooks are the only unauthenticated endpoints.

### 2.2 IDs, dates, money

- **IDs:** every object exposes `uuid` (string). Never expose integer PKs, and use UUIDs in URLs.
- **Dates:** date-only fields (`travel_date`, `pay_by_date`, `due_date`, `next_due_date`, `start_date`, `end_date`) are `"YYYY-MM-DD"`. Timestamps (`created_at`, `completed_at`) are ISO-8601 with timezone. Use `TIME_ZONE = "Africa/Dar_es_Salaam"`, compute "today" in that zone, and store UTC.
- **Money:**
  - Always an **integer in minor units** plus a currency code. Never use floats or `Decimal` with fractions in the API.
  - | Currency | Minor units per major | Example |
    |---|---|---|
    | `TZS` | 1 (whole shillings) | `480000` = TSh 480,000 |
    | `USD`, `EUR`, `GBP` | 100 | `128000` = $1,280.00 |
  - In the database use `BigIntegerField` for amounts and `CharField(max_length=3)` for currency.
- **Enums:** snake_case strings (see §3), sent exactly as listed.

### 2.3 Errors

The app reads the first key it finds, in this order: `error` → `detail` → `message` →
`non_field_errors` → the first field error. Use DRF's default shapes:

```json
{"detail": "Travel date is too soon: full payment is due 14 days before travel."}
{"amount": ["Minimum payment is TZS 5000."]}
```

| Status | When |
|---|---|
| 400 | Validation errors (bad amount, date, travellers…) |
| 401 | Missing or invalid Firebase token |
| 404 | Unknown uuid, or an object belonging to another user (never leak existence) |
| 409 | State conflict ("only drafts can be activated", "goal is cancelled and can't take payments") |
| 5xx | Server errors. The app shows a generic message. |

The messages are shown to users verbatim, so write them as short, friendly sentences.

### 2.4 Pagination

Only `GET /api/itineraries/` is paginated: `PageNumberPagination` with a page size of 10, and
the key **`results`** (do not rename it like salonchap does):

```json
{"count": 23, "next": "https://…/api/itineraries/?page=2", "previous": null, "results": [ … ]}
```

Every other list endpoint returns a **plain JSON array**.

### 2.5 Ownership

Every goal, payment, booking, notification and wishlist query is filtered by
`request.user`. Return 404 for other users' objects.

---

## 3. Enums

| Name | Values |
|---|---|
| Residency | `resident`, `non_resident` |
| AgeCategory | `adult`, `child` |
| AccommodationLevel | `budget`, `mid_range`, `luxury` |
| GoalStatus | `draft`, `active`, `paused`, `completed`, `cancelled`, `expired` |
| PaymentFrequency | `weekly` (7 days), `bi_weekly` (14 days), `monthly` (calendar month), `custom` (`custom_days`, default 30) |
| InstallmentStatus | `upcoming`, `paid`, `partially_paid`, `missed` |
| PaymentMethod | `mpesa`, `airtel_money`, `mixx_by_yas`, `halo_pesa`, `card` |
| PaymentStatus | `pending`, `success`, `failed`, `refunded` |
| BookingStatus | `confirmed`, `cancelled`, `completed` |
| KycStatus | `not_required`, `pending`, `verified`, `rejected` |
| TripDocumentType | `voucher`, `packing_list`, `operator_contacts`, `other` |
| Currency | `TZS`, `USD`, `EUR`, `GBP` |

---

## 4. Data model (Django)

All models get `uuid = UUIDField(default=uuid4, unique=True, editable=False)`,
`created_at`, and `updated_at`.

**userauth**
- `UserAccount(AbstractUser)`: `username` = Firebase uid, `full_name`, `phone_number`, `email`, `residency` (nullable), `preferred_currency` (nullable), `country` (default `"TZ"`), `kyc_status` (default `not_required`), `notifications_enabled` (default True).
- `DeviceToken`: user FK, `token` (unique), `platform` (`android`/`ios`), `notifications_enabled`. Same as salonchap.
- `KycDocument`: user FK, `document_type` (`nida`/`passport`), `document_number` (encrypted at rest), `status`, `reviewed_at`.

**catalogue**
- `Operator`: `name`, `lead_time_days` (nullable → default 14), `phone_number`, `whatsapp`, `email`, `refund_policy` (FK to a `RefundPolicy`, see §7.9).
- `Destination`: `name` (unique), `region`, `image`.
- `Itinerary`: `title`, `slug` (unique), `summary`, `destinations` (M2M Destination; serialize as list of names), `duration_days`, `accommodation_level`, `inclusions`/`exclusions` (ArrayField or JSON list of strings), `images` (JSON list of URLs, first = cover), operator FK, `min_group_size`, `max_group_size`, `is_active`.
- `ItineraryDay`: itinerary FK, `day_number`, `title`, `description`, `location`, `meals` (list), `accommodation`. Unique on (itinerary, day_number).
- `ItineraryPricing` (1:1 itinerary): `base_currency`, `resident_adult`, `resident_child`, `non_resident_adult`, `non_resident_child` (all BigInteger, minor units of `base_currency`).
- `SeasonalAdjustment`: pricing FK, `start_date`, `end_date` (inclusive), `multiplier_bps` (int, 10000 = 1.0×), `label`. If ranges overlap, the first match by `start_date` wins.

**goals**
- `SavingsGoal`:
  - Ownership and naming: user FK, itinerary FK, `title`.
  - Dates: `travel_date`, `pay_by_date`.
  - Money: `currency`, `total_amount`, `deposit_amount`, `amount_paid` (BigIntegers).
  - Plan: `frequency`, `custom_days`.
  - State: `status`, `consecutive_missed`, `completed_at`, `cancellation_reason`.
  - Locked at activation (see §7.2): `locked_fx_numerator`, `locked_fx_denominator`, `locked_pricing_snapshot` (JSON).
- `Traveller`: goal FK, `name`, `age_category`, `residency`, `position`.
- `Installment`: goal FK, `due_date`, `amount`, `amount_paid`, `status`, `is_deposit`, `position`.

**payments**
- `Payment`:
  - Links and amount: goal FK, user FK, `amount`, `currency`, `method`, `phone_number` (`255XXXXXXXXX`).
  - Provider details: `order_reference` (unique, client-supplied idempotency key), `provider`, `provider_reference`, `provider_txn_id`, `checkout_url`.
  - Outcome: `status`, `failure_reason`, `receipt_number` (unique, set on success), `raw_webhook` (JSON), `settled_at`.

**bookings**
- `Booking` (1:1 goal): `confirmation_code` (unique, e.g. `SC-7F3K2Q`), `status`, `travel_date`.
- `TripDocument`: booking FK, `type`, `title`, `url` (nullable, e.g. a PDF voucher), `content` (nullable text; one item per line for packing lists).

**notifications**
- `Notification`: user FK, goal FK (nullable), `title`, `message`, `type` (see §9), `is_read`.

**wishlist**
- `WishlistItem`: user FK, itinerary FK, unique together.

**core**
- `FxRate`: `from_currency`, `to_currency`, `numerator`, `denominator` (int, see §7.1), `fetched_at`.
- `AppSetting` (singleton, editable in admin):
  - `default_lead_time_days` = 14
  - `missed_before_pause` = 3
  - `min_payment_tzs` = 5000
  - `min_payment_other_major` = 10
  - `reminder_days_before_due` = 3
  - `pending_payment_timeout_minutes` = 15

---

## 5. Response objects (exact JSON)

### User
```json
{
  "uuid": "…", "full_name": "Asha Mushi", "phone_number": "+255712345678", "email": null,
  "residency": "resident", "preferred_currency": "TZS", "country": "TZ",
  "kyc_status": "not_required", "notifications_enabled": true,
  "created_at": "2026-10-18T09:12:00+03:00"
}
```
`full_name`, `residency` and `preferred_currency` are `null` until onboarding. The app shows
the profile-setup screen while any of them is missing.

### Itinerary
```json
{
  "uuid": "…", "title": "3-Day Serengeti & Ngorongoro", "slug": "3-day-serengeti-ngorongoro",
  "summary": "…", "destinations": ["Serengeti", "Ngorongoro"], "duration_days": 3,
  "accommodation_level": "mid_range",
  "days": [{"day_number": 1, "title": "…", "description": "…", "location": "Serengeti",
            "meals": ["lunch", "dinner"], "accommodation": "Serengeti Tented Camp"}],
  "inclusions": ["…"], "exclusions": ["…"], "images": ["https://…/cover.jpg", "…"],
  "operator_uuid": "…", "operator_name": "Kili Trails Safaris", "operator_lead_time_days": 14,
  "min_group_size": 1, "max_group_size": 6, "is_active": true,
  "pricing": {
    "base_currency": "USD",
    "resident_adult": 45000, "resident_child": 25000,
    "non_resident_adult": 128000, "non_resident_child": 72000,
    "seasonal_adjustments": [
      {"start_date": "2027-07-01", "end_date": "2027-10-31", "multiplier_bps": 12000, "label": "High season (+20%)"}
    ]
  },
  "display_price": 1170000, "display_currency": "TZS"
}
```
`display_price` is the per-adult price for the requested `residency` and `currency` (see §7.1).

### Destination
`{"name": "Serengeti", "region": "Northern circuit", "image": "https://…"}`

### SavingsGoal
```json
{
  "uuid": "…", "itinerary_uuid": "…", "title": "3-Day Serengeti & Ngorongoro",
  "travellers": [{"name": "Asha", "age_category": "adult", "residency": "resident"}],
  "travel_date": "2027-11-15", "pay_by_date": "2027-11-01",
  "currency": "TZS", "total_amount": 480000, "deposit_amount": 0, "amount_paid": 50000,
  "frequency": "monthly", "installment_amount": 38334, "next_due_date": "2026-11-18",
  "status": "active", "consecutive_missed": 0,
  "cover_image": "https://…", "booking_uuid": null,
  "created_at": "…", "completed_at": null,
  "installments": [
    {"uuid": "…", "due_date": "2026-11-18", "amount": 40000, "amount_paid": 40000,
     "status": "paid", "is_deposit": false}
  ]
}
```
- `installments` is ordered by `due_date`.
- `installment_amount` is the outstanding amount (`amount − amount_paid`) of the **next open** installment, and `next_due_date` is its due date. Both are `0`/`null` when nothing is open.

### GoalQuote (preview, nothing saved)
```json
{
  "currency": "TZS", "total_amount": 3993600, "deposit_amount": 0,
  "pay_by_date": "2027-08-01", "season_label": "High season (+20%)",
  "lines": [{"residency": "non_resident", "age_category": "adult", "count": 1,
             "unit_price": 3993600, "subtotal": 3993600}],
  "installments": [{"due_date": "2026-11-18", "amount": 399360, "is_deposit": false}]
}
```

### CancellationQuote
```json
{"currency": "TZS", "amount_paid": 200000, "refund_percentage": 90, "processing_fee": 5000,
 "refund_amount": 175000, "policy": "More than 60 days before travel: 90% refund. …"}
```

### Payment
```json
{
  "uuid": "…", "goal_uuid": "…", "goal_title": "…", "amount": 50000, "currency": "TZS",
  "method": "mpesa", "phone_number": "255712345678", "provider_reference": null,
  "status": "pending", "failure_reason": null, "receipt_number": null,
  "checkout_url": null, "created_at": "…"
}
```

### Booking
```json
{
  "uuid": "…", "goal_uuid": "…", "itinerary_uuid": "…", "itinerary_title": "…",
  "confirmation_code": "SC-7F3K2Q", "status": "confirmed", "travel_date": "2027-11-15",
  "documents": [
    {"type": "voucher", "title": "Safari voucher", "url": null, "content": "Confirmation: …"},
    {"type": "operator_contacts", "title": "Operator contacts", "url": null, "content": "…"},
    {"type": "packing_list", "title": "Packing list", "url": null, "content": "Hat\nSunscreen\n…"}
  ],
  "operator_contact": {"name": "…", "phone_number": "+255…", "email": "…", "whatsapp": "+255…"},
  "created_at": "…"
}
```

### Notification
`{"uuid": "…", "title": "…", "message": "…", "type": "payment_success", "goal_uuid": "…", "is_read": false, "created_at": "…"}`

---

## 6. Endpoints

### Users — `/api/users/`
| Method & path | Body | Response |
|---|---|---|
| `GET me/` | – | User. Creates the profile on first call. |
| `PATCH me/` | any of `full_name`, `email`, `phone_number`, `residency`, `preferred_currency`, `country`, `notifications_enabled` | User |
| `POST devices/` | `{"token": "…", "platform": "android"\|"ios"}` | `{"ok": true}`. Upsert on `token` and reassign it to the current user. |
| `POST kyc/` | `{"document_type": "nida"\|"passport", "document_number": "…"}` | `{"message": "…", "kyc_status": "pending"\|"verified"}` |
| `GET wishlist/` | – | `Itinerary[]`, with `display_price` for the user's residency and currency |
| `POST wishlist/{itinerary_uuid}/` | – | `{"message": "Saved to wishlist"}`. Idempotent. |
| `DELETE wishlist/{itinerary_uuid}/` | – | `{"message": "Removed from wishlist"}`. Idempotent. |

`PATCH me/` with a new `preferred_currency` affects **new** goals only.

### Catalogue — `/api/itineraries/`
| Method & path | Query | Response |
|---|---|---|
| `GET /` | `page`, `residency`, `currency`, `search`, `destination`, `min_days`, `max_days`, `min_price`, `max_price`, `accommodation_level`, `month` (1–12) | Paginated `Itinerary[]` (active only) |
| `GET {uuid}/` | `residency`, `currency` | Itinerary |
| `GET destinations/` | – | `Destination[]` |

Filter semantics:
- `residency` / `currency` default to the user's profile values, or `non_resident` / `USD` if those aren't set.
- `search` does a case-insensitive match on title and destination names.
- `destination` is an exact destination name.
- `min_days` / `max_days` are inclusive bounds on `duration_days`.
- `min_price` / `max_price` are minor units **in `currency`**, compared against `display_price`.
- `month` keeps itineraries that can still be booked for that month's next occurrence: the month's last day must be ≥ today + lead time + 7 days.
- Order: featured first (add an `is_featured` / `sort_order` admin field), then newest. The first 4 results appear in the app's "Popular this season" carousel.

### Goals — `/api/goals/`
| Method & path | Body | Response |
|---|---|---|
| `GET /` | query `status` (optional) | `SavingsGoal[]`, newest first |
| `POST quote/` | Plan body ↓ | GoalQuote (**nothing saved**) |
| `POST /` | Plan body ↓ plus optional `title` | **201** SavingsGoal, `status: "draft"`, `installments: []` |
| `GET {uuid}/` | – | SavingsGoal |
| `DELETE {uuid}/` | – | **204**. Drafts only, otherwise 409. |
| `POST {uuid}/activate/` | – | SavingsGoal (`active`, schedule built, **price locked**). Drafts only, otherwise 409. |
| `POST {uuid}/reschedule/` | `{"travel_date": "YYYY-MM-DD", "frequency": "monthly"}` (frequency optional) | SavingsGoal. Allowed when `active`, `paused` or `expired`. |
| `GET {uuid}/cancellation-quote/` | – | CancellationQuote |
| `POST {uuid}/cancel/` | `{"reason": "…"}` | CancellationQuote. Allowed when `draft`, `active`, `paused` or `expired`. |
| `GET {uuid}/payments/` | – | `Payment[]` for this goal, newest first |

**Plan body** (used by `quote/` and create):
```json
{
  "itinerary_uuid": "…",
  "travellers": [{"name": "Asha", "age_category": "adult", "residency": "resident"}],
  "travel_date": "2027-11-15",
  "currency": "TZS",
  "frequency": "monthly",
  "deposit_amount": 0,
  "custom_days": 30
}
```

Validation (400 with a friendly `detail`):
- The number of travellers is within `[min_group_size, max_group_size]`, with at least one adult.
- `travel_date` leaves at least one full period before pay-by (§7.3).
- `0 ≤ deposit_amount < total`.
- `currency` is supported and itinerary is active.

The app always calls create and then activate back-to-back, unless the user taps
"Save as draft".

### Payments — `/api/payments/`
| Method & path | Body | Response |
|---|---|---|
| `POST initiate/` | ↓ | **201** Payment (`pending`) |
| `GET /` | – | `Payment[]` for the user, newest first |
| `GET {uuid}/` | – | Payment. **The app polls this every 3 s for up to 3 min.** |

```json
{
  "goal_uuid": "…", "amount": 50000, "currency": "TZS", "method": "mpesa",
  "order_reference": "SC1729260000123A7F3", "phone_number": "255712345678"
}
```
See §7.6 for the rules. `phone_number` arrives normalised as `255` followed by 9 digits.

### Bookings — `/api/bookings/`
`GET /` → `Booking[]`; `GET {uuid}/` → Booking.

### Notifications — `/api/notifications/`
`GET /` → `Notification[]` (newest first); `POST {uuid}/read/` → `{"ok": true}`;
`POST read-all/` → `{"ok": true}`.

### Webhooks (no auth; verify signatures)
- `POST /api/payments/webhooks/clickpesa/`
- `POST /api/payments/webhooks/card/` (Stripe / Flutterwave / DPO, whichever you pick)

---

## 7. Business rules (must match the app exactly)

Port the Dart logic one-to-one into `apps/goals/services/`. The tests in §11 use the same
numbers as the app's Dart tests.

### 7.1 Money, FX and display price
- `FxRate` is rational: one major unit of `from` = `numerator / denominator` major units of `to`.
- Converting minor units:
  ```
  to_minor = ceil( from_minor × numerator × to.minor_per_major
                   / (denominator × from.minor_per_major) )
  ```
  Use Python integers (arbitrary precision) and round **up**.
- Store rates as TZS-per-unit, e.g. USD=2600/1. Cross rates: `from→to = tzs_per[from] / tzs_per[to]`. Refresh daily via Celery from a provider (e.g. Bank of Tanzania or exchangerate.host).
- `display_price` = convert(`price_for(residency, adult)`) at today's rate. No season multiplier.

### 7.2 Total cost & price lock
For each traveller category (residency × age):
```
unit_base   = pricing[residency_age]                                  # base currency, minor
unit_season = ceil(unit_base × multiplier_bps / 10000)                # season for travel_date
unit_goal   = convert(unit_season, base → goal currency)              # §7.1, rounded up
subtotal    = unit_goal × count
total       = Σ subtotals
```
- The season is applied per person **before** conversion, so `unit × count` equals the subtotal exactly.
- **Quote/create:** compute with current prices and FX.
- **Activate:** recompute with current prices and FX, then **lock**. Save `total_amount`, the FX numerator/denominator and a pricing snapshot. After activation, itinerary price or FX changes never touch the goal.
- **Currency lock:** `goal.currency` never changes. Every payment must be in that currency.

### 7.3 Pay-by date & validation
- `pay_by_date = travel_date − (operator.lead_time_days or 14)`.
- Period step: weekly is +7 days, bi_weekly is +14 days, custom is `+custom_days`. Monthly is +1 calendar month, clamped to the end of the month (Jan 31 → Feb 28/29), and each step starts from the previous due date.
- Due dates are `today + 1 period, + 2 periods, …` while `≤ pay_by_date`.
- Reject with 400 if `pay_by_date ≤ today`: "Travel date is too soon: full payment is due N days before travel."
- Reject with 400 if there are no due dates: "Not enough time for a weekly plan. Choose a later travel date or a shorter frequency."

### 7.4 Schedule generation (on activate)
```
entries = []
if deposit > 0: entries.append(due=today, amount=deposit, is_deposit=True)
dates     = due_dates(today, pay_by, frequency)
remaining = total − deposit
min_pay   = minimum_payment(currency)              # §7.6
max_periods = remaining // min_pay
if max_periods < 1:            dates = [dates[0]]
elif max_periods < len(dates): dates = dates[-max_periods:]    # keep the LATEST dates
parts = split(remaining, len(dates))
```
`split(remaining, n)`:
- Every part is `each = ceil(remaining / n)`, except the last, which takes whatever is left.
- Stop when nothing is left, so tail parts of zero are dropped.
- Examples: `split(100, 3) = [34, 34, 32]`, `split(5, 4) = [2, 2, 1]`.
- The parts always sum exactly to `remaining`.

### 7.5 Applying a successful payment
1. Walk open installments (`upcoming` / `partially_paid`) in due-date order and fill each one's outstanding amount until the payment is used up. A fully covered installment becomes `paid`; a partly covered one becomes `partially_paid`. Overpayment flows into the next installments.
2. `amount_paid += amount`, `consecutive_missed = 0`, and `paused → active`.
3. Recompute `installment_amount` and `next_due_date` (§5).
4. If `amount_paid ≥ total_amount`, complete the goal (§7.10).
5. Do all of this inside `transaction.atomic()` with `select_for_update()` on the goal. Webhooks can arrive twice or in parallel.

### 7.6 Payment initiation rules (`POST /api/payments/initiate/`)
1. **Idempotency:** if `order_reference` exists for this user, return that payment unchanged with 201.
2. The goal must be `active` or `paused`, otherwise 409 "This goal is {status} and can't take payments."
3. `currency` must equal `goal.currency`, otherwise 400.
4. `amount > remaining` → 400 "Amount is more than the remaining balance."
5. `amount < min_payment` and `amount ≠ remaining` → 400 "Minimum payment is TZS 5000." The minimum is TSh 5,000 for TZS and 10 major units for others, both from `AppSetting`.
6. Method must match the currency: TZS → mobile money only; others → `card` only.
7. Mobile money needs `phone_number` (`^255[67]\d{8}$`).
8. Create `Payment(status=pending)` and call the provider:
   - **Mobile money (ClickPesa, as in salonchap):** initiate a USSD push with `orderReference = order_reference`, `amount` in TZS, `phoneNumber` = 255…, and cache the JWT in Redis with a lock as `utils/clickpesa.py` does. On a synchronous provider error, mark the payment `failed` with a friendly `failure_reason` and still return it.
   - **Card:** create a hosted checkout session and return its URL in `checkout_url`. The app opens it in the browser and keeps polling.
9. The client **never** decides the outcome. Only webhooks (or reconciliation, §8) move a payment to `success` or `failed`.

### 7.7 Webhooks
- Verify the signature or shared secret. salonchap's ClickPesa webhook doesn't; fix that here. Reject unverified calls with 401.
- Look up the payment by `order_reference` and ignore it if already final, which makes handling idempotent.
- On `SUCCESS`: set `status=success`, `provider_reference`, `settled_at`, and a unique `receipt_number` (e.g. `SC-RCPT-XXXXXXXX`). Then apply §7.5, create a `payment_success` notification and push.
- On `FAILED`: set `status=failed` and a `failure_reason`, then create a `payment_failed` notification and push. The goal is unchanged.
- Store the raw payload in `raw_webhook`.

### 7.8 Missed installments, pause, expiry (daily Celery task)
For each `active`/`paused` goal, with today in Africa/Dar_es_Salaam:
1. Every open installment with `due_date < today` becomes `missed`. Its shortfall is `amount − amount_paid`, and its `amount` is set to `amount_paid` so the schedule still sums to the total.
2. Add the total shortfall to the remaining future open installments and re-split it across them with `split()`, keeping their due dates. A fully covered future entry with nothing paid is deleted.
3. `consecutive_missed += newly_missed`. Send an `installment_missed` notification.
4. If `consecutive_missed ≥ missed_before_pause` (3) and the goal is `active`, set it to `paused` and send `goal_paused`.
5. If `today > pay_by_date` and `amount_paid < total_amount`, set it to `expired` and send `goal_expired`. The user can reschedule or cancel.

Paused goals still accept payments. Any successful payment resets `consecutive_missed` and
reactivates the goal (§7.5).

### 7.9 Reschedule & cancellation
- **Reschedule:**
  - Validate the new date as in §7.3.
  - The price stays locked. Keep paid entries (collapse any partially paid ones to their paid amount and mark them `paid`), then generate a fresh schedule for `total − amount_paid` from today.
  - Set the new `travel_date`, `pay_by_date` and `frequency`, plus `status=active` and `consecutive_missed=0`.
- **Refund policy:**
  - Configurable per operator, with a global default:
    ```
    days_to_travel > 60  → 90%
    31–60                → 50%
    ≤ 30                 → 0%
    processing_fee = ceil(amount_paid × 2.5%)
    refund_amount  = max(0, floor(amount_paid × pct / 100) − processing_fee)
    ```
  - Return the human-readable text in `policy`.
- **Cancel:**
  - Set `status=cancelled` and store `reason`.
  - Create a refund record and process it via the provider's payout or refund API in a Celery task, marking refunded payments `refunded`.
  - Send a `goal_cancelled` notification. Refund logic lives only on the backend.

### 7.10 Completion → Booking
When `amount_paid ≥ total_amount`:
- Set `status=completed`, `completed_at=now`, `next_due_date=null`.
- Create a `Booking` with a unique `confirmation_code` (`SC-` plus 6 uppercase alphanumerics), `status=confirmed` and the goal's `travel_date`.
- Create documents: `voucher` (code, trip, date, number of travellers, operator), `operator_contacts`, `packing_list` (see `mockPackingList` in the app's seed file), plus `operator_contact`.
- Set `goal.booking_uuid`.
- Notify with `goal_completed` ("Trip confirmed! 🎉"). Optionally email the operator.
- If KYC is required for the itinerary, set `kyc_status=pending` if not yet verified. The app then shows an "Add your NIDA/passport" prompt on the booking screen.

---

## 8. Celery beat schedule

| Task | Schedule | Purpose |
|---|---|---|
| `goals.tasks.process_missed_and_expired` | daily 00:15 EAT | §7.8 |
| `goals.tasks.send_due_reminders` | daily 09:00 EAT | `installment_due` push N days before (`reminder_days_before_due`, default 3) and on the due day |
| `payments.tasks.reconcile_pending_payments` | every 2 min | Query the provider status for `pending` payments older than 1 min, settle them as in §7.7, and fail them after `pending_payment_timeout_minutes` |
| `core.tasks.refresh_fx_rates` | daily 06:00 EAT | §7.1 |
| `payments.tasks.process_refunds` | every 10 min | §7.9 |

Respect `user.notifications_enabled` for **reminder** pushes. Always send payment results.

---

## 9. Push notifications (FCM)

- Send with `firebase_admin.messaging`, reusing salonchap's `send_push_notification` and its cleanup of invalid tokens.
- Payload:
  ```python
  messaging.Message(
      token=device.token,
      notification=messaging.Notification(title=title, body=message),
      data={"goal_uuid": str(goal.uuid), "type": notification_type},
  )
  ```
  The app reads `data["goal_uuid"]` to open the goal screen.
- **Device ID:** the app uses `firebase_messaging` 17, so the value posted to `/users/devices/` comes from `FirebaseMessaging.onRegistered` (a Firebase Installation ID). Confirm the FCM HTTP v1 targeting for that ID when you integrate, and fall back to treating it as a registration token.
- Always write a `Notification` row too, because the app's in-app list reads from it. Its `type` is one of `payment_success`, `payment_failed`, `installment_due`, `installment_missed`, `goal_completed`, `goal_paused`, `goal_expired`, `goal_cancelled`.

---

## 10. Admin & seed data

- Django admin covers Operators, Destinations, Itineraries (with inline Days and Pricing/Seasons), AppSetting, FxRate, Goals (read-mostly, with inline installments and payments), Payments and Bookings. The MVP uses admin-seeded itineraries; there is no operator portal.
- Port `lib/src/data/mock/mock_seed.dart` (6 itineraries, 9 destinations, the season ranges and the packing list) into a fixture or a `manage.py seed_catalogue` command, so the real API returns the same catalogue the app was designed with.

---

## 11. Tests that must pass (parity with the app)

```python
assert split(100, 3) == [34, 34, 32]
assert split(5, 4) == [2, 2, 1]
assert add_period(date(2026, 1, 31), "monthly") == date(2026, 2, 28)
assert pay_by(date(2026, 8, 15), 14) == date(2026, 8, 1)
# $1,280 non-resident adult × 1.2 season → TZS at 2600/1
assert quote_total(..., travel_date=high_season, currency="TZS") == 3_993_600
# TSh 1,000 → USD at 1/2600 rounds UP to 39 cents
assert convert(1000, "TZS", "USD", 1, 2600) == 39
# generated schedule always sums to total (with and without deposit)
# overpayment: [100,100,100] pay 150 → paid, partially_paid(50 left), upcoming
# missed: rolled shortfall keeps future sum == remaining; 3 misses → paused
# payment above remaining → 400; below minimum (and ≠ remaining) → 400
# duplicate order_reference → same payment returned, single charge
# duplicate webhook → applied once
# paying full balance → goal completed + exactly one booking
```
Also add API tests for ownership (another user's uuid returns 404) and for the exact JSON
keys in §5.

---

## 12. Security & ops checklist

- **Secrets:** never commit secrets. Load the Firebase service account, ClickPesa keys and card gateway keys from environment or a mounted secret. (salonchap_api has the admin SDK JSON committed under `secrets/`. Don't copy that.)
- **Logging:** don't log ID tokens (salonchap's auth class `print`s them), and don't return `str(e)` from auth failures to clients.
- **Webhooks:** verify signatures, process idempotently, and wrap balance updates in transactions with row locks.
- **KYC:** encrypt `document_number` and limit access to it in admin.
- **Rate limits:** throttle `payments/initiate/` and auth-sensitive endpoints.
- **Production:** `ALLOWED_HOSTS`, HTTPS, CORS, Swagger behind auth in prod, Prometheus metrics, Sentry.

---

## 13. Hooking the app up

1. In the app, set `AppConfig._dev` and `_prod` in `lib/src/core/utils/app_config.dart` to the API base URL, with no trailing slash.
2. Run `flutterfire configure`. Use the **same Firebase project** for the app and the backend's service account.
3. Run the app with `flutter run --dart-define=USE_MOCK_API=false`.
4. Smoke test:
   1. Sign in, complete the profile and browse the catalogue (prices should change with residency and currency).
   2. Quote a goal, start saving, pay with mobile money, approve on the phone, then watch the status screen flip to success and the goal update.
   3. Pay the full balance; the booking and its documents should appear.

---

## 14. Admin dashboard API (`/api/admin/`)

Used by the Flutter Web dashboard (`safarichap_admin`). Customer endpoints above are unchanged.

### 14.1 Access model

- **Auth:** the same `Authorization: Bearer <Firebase ID token>` as the app. Staff sign in with Firebase email + password.
- **Who is staff:** a `UserAccount` with `is_staff=True` **and** an active `StaffProfile` (`apps/adminpanel`). Everyone else gets **403** on every `/api/admin/` endpoint. Bad or missing tokens stay **401**.
- **Permissions:** codes like `payments.reconcile`. They're defined once in `apps/adminpanel/permissions.py` (`PERMISSIONS`) and synced into the DB by `manage.py seed_rbac`, which both entrypoints run.
  - A staff member's codes are the union of their roles' codes, cached for 60 s and cleared on any role or staff change.
  - Django superusers with a staff profile get every code.
- **Views** declare `view_permission` (GET), `manage_permission` (writes) and per-action overrides (`action_permissions`). `HasAdminPermission` enforces them.
- **Built-in roles** (`SYSTEM_ROLES`): Super Admin, Operations, Finance, Support, Content, Viewer.
  - Super Admin always has every code and can't be edited.
  - The other built-in roles can have their permissions edited but can't be renamed or deleted. `seed_rbac` only sets their defaults on first creation.
- **Guards:** you can't deactivate or remove yourself. At least one active Super Admin must always remain (409 otherwise).
- **Audit:** every write goes through `adminpanel.services.audit()`, which stores actor, action (e.g. `goal.pause`), target, before/after JSON and IP in `AuditLog`.
- **First admin:** `python manage.py create_super_admin --email you@safarichap.co.tz --name "You"`. It creates the Firebase user if needed and prints a password-setup link.

### 14.2 Conventions

- Lists are paginated: `?page=` and `?page_size=` (default 25, max 200), returning `{count, next, previous, results}`.
  - Roles and refund policies return a plain list.
- `?search=` searches text fields, `?ordering=field` / `-field` sorts, and filters are exact fields (e.g. `?status=active`, `?created_at__gte=2026-01-01`).
- Objects are addressed by `uuid`. Money is integer minor units plus `currency`, as everywhere else.
- Errors use the same shapes as §2.3. A **409** means the object's state doesn't allow the action.

### 14.3 Endpoints

| Area | Endpoint | Permission |
|---|---|---|
| Session | `GET me/` → `{user, roles[], permissions[]}` | any staff |
| Permissions | `GET permissions/` | `roles.view` |
| Roles | `GET/POST roles/`, `PATCH/DELETE roles/{uuid}/` (`permissions` = list of codes) | `roles.view` / `roles.manage` |
| Staff | `GET staff/`; `POST staff/` `{email, full_name, roles[uuid]}` → staff + `password_link` (also emailed); `PATCH staff/{uuid}/` `{full_name?, roles?, is_active?}`; `DELETE staff/{uuid}/` (removes dashboard access only) | `staff.view` / `staff.manage` |
| Audit | `GET audit-logs/` (`action`, `action__startswith`, `target_type`, `target_id`, `actor__uuid`, `created_at__gte/lte`) | `audit.view` |
| Overview | `GET stats/?days=30` (counts, money per currency, daily collections and sign-ups, top trips) | `reports.view` |
| Customers | `GET users/`, `GET users/{uuid}/` (+ goals, payments, devices, KYC docs), `PATCH users/{uuid}/`, `GET users/export/` (CSV, same filters) | `users.view` / `users.manage` / `users.export` |
| KYC | `GET kyc/?status=pending`, `POST kyc/{uuid}/approve/` / `reject/` `{note}`. Sets the user's `kyc_status` and notifies them | `kyc.view` / `kyc.review` |
| Goals | `GET goals/`, `GET goals/{uuid}/` (+ installments, payments, refunds, `cancellation_quote`), `POST goals/{uuid}/pause/`, `resume/`, `reschedule/` `{travel_date, frequency?}`, `cancel/` `{reason}` | `goals.view` / `goals.manage` |
| Payments | `GET payments/`, `GET payments/{uuid}/` (`raw_webhook` only with `payments.view_raw`), `POST payments/{uuid}/reconcile/` (pending only) | `payments.view` / `payments.reconcile` |
| Refunds | `GET refunds/`, `POST refunds/{uuid}/process/` (pending/failed, ignores the 5-attempt cap), `POST refunds/{uuid}/mark-completed/` `{provider_reference}` (manual payout) | `refunds.view` / `refunds.manage` |
| Bookings | `GET bookings/`, `GET/PATCH bookings/{uuid}/` `{status}`, `POST bookings/{uuid}/documents/`, `POST bookings/{uuid}/notify/`, `PATCH/DELETE trip-documents/{uuid}/` | `bookings.view` / `bookings.manage` |
| Catalogue | CRUD on `operators/`, `destinations/`, `refund-policies/`, `itineraries/`. A trip is written whole: `destinations` (ordered uuids), `days`, and `pricing` with `seasonal_adjustments` replace what's stored. Deleting something still in use → 409 | `catalogue.view` / `catalogue.manage` |
| Uploads | `POST uploads/` multipart `{file, folder}` → `{url}`. JPG/PNG/WebP/PDF ≤ 10 MB; `folder` = `itineraries`/`destinations` (catalogue.manage) or `documents` (bookings.manage) | per folder |
| FX | `GET fx-rates/`, `GET fx-rates/current/`, `POST fx-rates/` `{from_currency, numerator, denominator}` (manual rate), `POST fx-rates/refresh/` (queues the provider fetch) | `fx.view` / `fx.manage` |
| Settings | `GET/PATCH settings/` (the `AppSetting` singleton) | `settings.view` / `settings.manage` |
| Notifications | `GET notifications/` (everything customers received), `GET broadcasts/`, `POST broadcasts/` `{title, message, audience: all\|residency\|goal_status\|users, residency?, goal_status?, user_uuids?, dry_run?}` | `notifications.view` / `notifications.send` |

### 14.4 Rules the admin actions keep

- **Reschedule and cancel** call the same `goals.services` functions as the app: the price stays locked, refunds follow the refund policy, and the customer is notified.
- **Pause and resume** only flip `active` ↔ `paused`. Resume resets `consecutive_missed`.
- **Reconcile** uses `payments.services.reconcile_payment`, the same path as the 2-minute task, so settlement stays idempotent.
- **Trip edits** never touch active goals: their price was snapshotted at activation.
- **New notification types:** `kyc_verified`, `kyc_rejected`, `booking_updated`, `announcement`. The app reads `type` as a plain string, so older app builds still list them.
