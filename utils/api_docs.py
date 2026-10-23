"""
OpenAPI (Swagger / ReDoc) building blocks: the API overview, tag groups,
shared error and response shapes, and the schema class that adds the
401/429 responses every endpoint can return.
"""
from drf_yasg import openapi
from drf_yasg.generators import OpenAPISchemaGenerator
from drf_yasg.inspectors import SwaggerAutoSchema
from rest_framework import serializers
from rest_framework.permissions import AllowAny

from apps.core.choices import Residency
from utils.money import CURRENCY_CHOICES

API_DESCRIPTION = """
Backend for the SafariChap app: browse safari trips, save towards one with an
installment plan, pay by mobile money or card, and get a confirmed booking
with trip documents once the goal is fully paid.

## Authentication
Send the signed-in user's Firebase ID token on every request:

    Authorization: Bearer <Firebase ID token>

The user profile is created on the first authenticated call. A missing,
invalid or expired token returns **401**; the app refreshes the token and
retries once. 401 is never used for business errors. Payment-provider
webhooks are the only unauthenticated endpoints.

## Money
All amounts are **integers in minor units** of their currency: TZS has no
minor unit (`5000` = TSh 5,000), USD/EUR/GBP use cents (`12800` = $128.00).
Supported currencies: TZS, USD, EUR, GBP.

## Prices and currency
Trip prices are shown for a **residency** (`resident` / `non_resident`) and a
display **currency**. Both come from the query string, then the user's
profile, then fall back to `non_resident` / `USD`. A goal's price and FX rate
are locked when it is activated.

## Goal lifecycle
`draft` → `active` (price locked, schedule built) → `completed` (fully paid,
booking created). Active goals become `paused` after repeated missed
installments and resume on the next payment; they become `expired` when the
pay-by date passes unpaid, and can be rescheduled. Drafts, active, paused and
expired goals can be `cancelled` (refund per the operator's policy).

## Errors
Errors return JSON with a message the app shows as-is:

| Status | Body | When |
|---|---|---|
| 400 | `{"detail": "..."}` or `{"field": ["..."]}` | Invalid input or a business rule failed |
| 401 | `{"detail": "..."}` | Missing, invalid or expired token |
| 404 | `{"detail": "..."}` | Not found, or not the user's |
| 409 | `{"detail": "..."}` | The object's state doesn't allow this action |
| 429 | `{"detail": "Request was throttled. Expected available in N seconds."}` | Rate limit hit |

## Rate limits
Every signed-in user gets **120 requests/min** overall. Some endpoints have a
tighter limit on writes, noted on each endpoint: quotes 60/min, goal changes
20/min, payments 20/min, profile and devices 10/min, KYC 5/min. Over the
limit you get **429** with a `Retry-After` header. nginx also limits each IP to
20 requests/s (bursts of 40).

## Pagination
Only the trip list is paginated (`?page=`, 10 per page, standard
`count` / `next` / `previous` / `results`). Other lists return everything,
newest first.
"""

TAGS = [
    {'name': 'Account', 'description': "The signed-in user's profile, push devices and identity (KYC)."},
    {'name': 'Trips', 'description': "The safari catalogue, priced for the user's residency and currency."},
    {'name': 'Wishlist', 'description': "Trips the user has saved for later."},
    {'name': 'Goals', 'description': "Savings goals: quote, create, activate, reschedule and cancel."},
    {'name': 'Payments', 'description': "Paying into a goal by mobile money (ClickPesa) or card (Flutterwave)."},
    {'name': 'Bookings', 'description': "Confirmed trips with vouchers and documents, created when a goal is fully paid."},
    {'name': 'Notifications', 'description': "The in-app notification list (each one is also sent as a push)."},
    {'name': 'Webhooks', 'description': "Called by payment providers, not the app. Authenticated by a shared secret."},
]
TAG_GROUPS = [
    {'name': 'App', 'tags': ['Account', 'Trips', 'Wishlist', 'Goals', 'Payments', 'Bookings', 'Notifications']},
    {'name': 'Integrations', 'tags': ['Webhooks']},
]

# Tag for each app's views; webhook views are tagged in their decorators.
MODULE_TAGS = {
    'apps.userauth.views': 'Account', 'apps.catalogue.views': 'Trips', 'apps.wishlist.views': 'Wishlist',
    'apps.goals.views': 'Goals', 'apps.payments.views': 'Payments', 'apps.bookings.views': 'Bookings',
    'apps.notifications.views': 'Notifications',
}


class ApiSchemaGenerator(OpenAPISchemaGenerator):
    def get_schema(self, request=None, public=False):
        schema = super().get_schema(request, public)
        schema['tags'] = TAGS
        schema['x-tagGroups'] = TAG_GROUPS  # ReDoc sidebar sections
        return schema


class ApiAutoSchema(SwaggerAutoSchema):
    """Tags by app, and adds the 401/429 responses every endpoint can return."""

    def get_tags(self, operation_keys=None):
        if self.overrides.get('tags'):
            return self.overrides['tags']
        return [MODULE_TAGS.get(type(self.view).__module__, 'Other')]

    def get_response_serializers(self):
        responses = super().get_response_serializers()
        public = any(p is AllowAny for p in self.view.permission_classes)
        if not public:
            responses.setdefault('401', openapi.Response("Missing, invalid or expired Firebase token.", ErrorSerializer))
        if self.view.get_throttles():
            responses.setdefault('429', openapi.Response("Rate limit hit; see the `Retry-After` header.",
                                                         ErrorSerializer))
        return responses


# ── Shared shapes ───────────────────────────────────────────────────────

class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="A message safe to show to the user.")


class OkSerializer(serializers.Serializer):
    ok = serializers.BooleanField(default=True)


class MessageSerializer(serializers.Serializer):
    message = serializers.CharField()


VALIDATION_ERROR = openapi.Response(
    "Invalid input. Either `{\"detail\": \"...\"}` for a business rule, or field errors like "
    "`{\"phone_number\": [\"Enter a valid mobile money number.\"]}`.",
    openapi.Schema(type=openapi.TYPE_OBJECT, additional_properties=openapi.Schema(
        type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_STRING))),
)
NOT_FOUND = openapi.Response("Not found, or it belongs to another user.", ErrorSerializer)
CONFLICT = openapi.Response("The object's current state doesn't allow this action.", ErrorSerializer)

RESIDENCY_PARAM = openapi.Parameter(
    'residency', openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=Residency.values,
    description="Price for this residency. Default: the user's profile, then `non_resident`.",
)
CURRENCY_PARAM = openapi.Parameter(
    'currency', openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=[c for c, _ in CURRENCY_CHOICES],
    description="Show `display_price` in this currency. Default: the user's profile, then `USD`.",
)


def rate_limit_note(scope_rate: str) -> str:
    return f"\n\n**Rate limit:** {scope_rate} per user, on top of the global 120/min."
