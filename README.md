# SafariChap API

Django backend for the SafariChap Flutter app (save towards a safari in installments, then get a confirmed booking).
It uses the same stack and layout as `salonchap_api`. The full contract is in [docs/BACKEND_GUIDE.md](docs/BACKEND_GUIDE.md).

- Python 3.12, Django 5.2, DRF 3.16, PostgreSQL 16
- Celery 5 + django-celery-beat, with Redis as broker, cache and locks
- `firebase_admin` for verifying ID tokens and sending FCM pushes
- ClickPesa for mobile money (USSD push and payouts), Flutterwave hosted checkout for cards
- drf-yasg (`/swagger/`), django-prometheus (`/metrics`), Docker Compose with nginx, Prometheus and Grafana

## Layout

```
config/settings/{base,development,production,test}.py   celery.py  urls.py
apps/
  userauth/       UserAccount, DeviceToken, KycDocument (encrypted), FirebaseAuthentication
  catalogue/      Operator, RefundPolicy, Destination, Itinerary(+Day, Pricing, SeasonalAdjustment), seed_catalogue
  goals/          SavingsGoal, Traveller, Installment, services/{pricing,schedule,goals}.py, daily tasks
  payments/       Payment, Refund, initiation, webhooks, reconciliation and refund tasks
  bookings/       Booking, TripDocument
  notifications/  Notification + notify() (DB row + FCM push)
  wishlist/       WishlistItem (/api/users/wishlist/)
  adminpanel/     Dashboard API (/api/admin/): roles + permission codes, StaffProfile, AuditLog, Broadcast
  core/           FxRate, AppSetting (configurable rules), enums, FX refresh task
utils/            firebase, clickpesa, card_gateway, money, order_reference, pagination_util, encryption
docker/           Dockerfiles, entrypoints, nginx, prometheus
```

The business rules in `apps/goals/services/schedule.py` and `pricing.py` are one-to-one ports of the app's
`schedule_calculator.dart` and `pricing_calculator.dart`. If you change one side, change the other too.

## Run with Docker (dev)

```bash
cp .env.example .env            # fill in DB_* and DJANGO_SECRET_KEY at least
mkdir -p secrets && cp ~/Downloads/<firebase-adminsdk>.json secrets/firebase-adminsdk.json
docker compose -f docker-compose.dev.yaml up --build
```

On start, the dev entrypoint runs the migrations and `seed_catalogue`, which loads the app's 6 itineraries,
9 destinations, seasons, operators and default FX rates. The API is served on http://localhost:8000 (and on :8080
through nginx), with Swagger at `/swagger/`, Prometheus on :9090 and Grafana on :3001.

Create an admin user with `docker compose -f docker-compose.dev.yaml exec app python manage.py createsuperuser`.

For the admin dashboard (`../safarichap_admin`), give a Firebase email account the Super Admin role. This creates the
Firebase user if needed and prints a link to set its password:

```bash
docker compose -f docker-compose.dev.yaml exec app python manage.py create_super_admin --email you@safarichap.co.tz --name "You"
```

Everyone else is invited from the dashboard (Staff → Invite). Roles and permissions are described in
[docs/BACKEND_GUIDE.md §14](docs/BACKEND_GUIDE.md).

## Run locally (no Docker)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # point DB_HOST/REDIS_URL at local services
.venv/bin/python manage.py migrate && .venv/bin/python manage.py seed_catalogue
.venv/bin/python manage.py runserver 0.0.0.0:8000
.venv/bin/celery -A config.celery worker -l info
.venv/bin/celery -A config.celery beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## Tests

The tests run on SQLite with eager Celery, so they need neither Postgres nor Redis:

```bash
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py test
```

They cover the §11 parity cases (split, monthly clamp, pay-by, the 3,993,600 TZS quote, FX rounding up,
overpayment, missed rollover and pause, minimum and remaining checks, idempotent `order_reference`, duplicate
webhooks, completion creating exactly one booking). They also check ownership (404) and the exact JSON keys from §5.

## Payments setup

| Provider | Webhook URL | Verification |
|---|---|---|
| ClickPesa (TZS, mobile money) | `https://<host>/api/payments/webhooks/clickpesa/?secret=<CLICK_PESA_WEBHOOK_SECRET>` | Shared secret in the URL, compared in constant time. Unverified calls get 401. |
| Flutterwave (USD/EUR/GBP, card) | `https://<host>/api/payments/webhooks/card/` | `verif-hash` header must equal `FLUTTERWAVE_WEBHOOK_HASH`. The outcome is then re-checked with `verify_by_reference`. |

- Webhooks and `reconcile_pending_payments` (every 2 minutes) both go through `payments.services.settle_payment`.
  It locks the payment row and then the goal row, and does nothing if the payment is already final, so duplicate
  or parallel webhooks are applied once.
- Pending payments that the provider never confirms are failed after `AppSetting.pending_payment_timeout_minutes`.
- Cancelling a goal creates a `Refund`, and `process_refunds` (every 10 minutes) sends it. TZS refunds go out as a
  ClickPesa mobile payout to the number that last paid. Card refunds use Flutterwave transaction refunds. When the
  refund completes, the goal's payments are marked `refunded`.
- If money arrives after a goal has been cancelled or completed, the payment is recorded and refunded in full.

## Celery beat (EAT)

| Task | Schedule |
|---|---|
| `apps.goals.tasks.process_missed_and_expired` | daily 00:15 |
| `apps.goals.tasks.send_due_reminders` | daily 09:00 |
| `apps.payments.tasks.reconcile_pending_payments` | every 2 min |
| `apps.core.tasks.refresh_fx_rates` | daily 06:00 (open.er-api.com by default; override with `FX_PROVIDER_URL`) |
| `apps.payments.tasks.process_refunds` | every 10 min |

## Monitoring (Grafana)

Grafana (:3001; dev login `admin` / `admin`) starts with its data sources and dashboards already loaded from
`docker/grafana/`:

- **Infrastructure:** Django API, Server (Node Exporter), PostgreSQL and Celery tasks, all from Prometheus.
- **SafariChap business:** payments, settlement, goals, refunds, notifications and broadcasts. These panels query
  Postgres directly through a read-only user (`grafana_ro`). The user can only read the columns listed in
  `apps/core/management/commands/setup_grafana_db_user.py`, so no phone numbers, emails, webhook payloads or KYC
  data. Both entrypoints create or update it on start. In production, set `GRAFANA_DB_PASSWORD` in `.env`. In dev it
  defaults to `grafana-dev`.

To change a dashboard, edit it in Grafana, then use **Export → Export as JSON → Download file** and save it over the
file in `docker/grafana/dashboards/<folder>/`. New JSON files there appear within 30 s. A business panel that needs a
new column must first have it added to `GRANTS` in that command.

## Deviations from salonchap_api (on purpose, per guide §12)

- No secrets in the repo. The Firebase service account comes from `FIREBASE_CREDENTIALS_PATH` or
  `FIREBASE_CREDENTIALS_JSON`, and SMTP and provider keys come from the environment.
- The auth class never logs tokens or returns provider errors. It returns 401 (not 403) for bad or missing tokens.
- Webhooks are verified. Webhook handling and balance updates are idempotent and use row locks.
- Pagination keeps DRF's `results` key. Every other list endpoint returns a plain array.
- PostGIS, Channels and Daphne were dropped because nothing here needs them. `production.py` imports `base`
  and turns on HTTPS, HSTS and Sentry. Swagger is staff-only in production.

## Hooking up the app

Set `AppConfig._dev` and `_prod` in the app's `lib/src/core/utils/app_config.dart` to this API's base URL, with no
trailing slash. Use the same Firebase project for the app and for this backend's service account. Then run
`flutter run --dart-define=USE_MOCK_API=false`.
