"""
Card payments through Flutterwave Standard (hosted checkout).

- create_checkout(): returns the hosted payment link (Payment.checkout_url)
- verify_by_reference(): authoritative status lookup by our order_reference (tx_ref)
- refund(): refunds part or all of a settled transaction
- verify_webhook(): checks the `verif-hash` header against the dashboard secret hash
"""
import hmac
import logging

import requests
from django.conf import settings

from utils.exceptions import ProviderError
from utils.money import minor_per_major

logger = logging.getLogger(__name__)

TIMEOUT = 20

SUCCESS_STATUSES = {'successful'}
FAILED_STATUSES = {'failed', 'cancelled'}


def _headers():
    return {
        "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _major(amount_minor: int, currency: str) -> str:
    factor = minor_per_major(currency)
    if factor == 1:
        return str(amount_minor)
    major, minor = divmod(amount_minor, factor)
    return f"{major}.{minor:02d}"


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(
            method, f"{settings.FLUTTERWAVE_BASE_URL}{path}", headers=_headers(), timeout=TIMEOUT, **kwargs
        )
    except requests.exceptions.Timeout:
        raise ProviderError("Flutterwave timeout", "The card provider took too long to respond. Please try again.")
    except requests.exceptions.RequestException as e:
        raise ProviderError(f"Flutterwave request failed: {type(e).__name__}")
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code not in (200, 201) or body.get('status') != 'success':
        logger.warning("Flutterwave %s %s returned %s: %s", method, path, response.status_code, body.get('message'))
        raise ProviderError(
            f"Flutterwave {path} returned {response.status_code}",
            "We couldn't start a card checkout. Please try again.",
        )
    return body.get('data') or {}


def create_checkout(order_reference: str, amount: int, currency: str, user, title: str) -> str:
    data = _request('POST', '/payments', json={
        "tx_ref": order_reference,
        "amount": _major(amount, currency),
        "currency": currency,
        "redirect_url": settings.CARD_CHECKOUT_REDIRECT_URL,
        "payment_options": "card",
        "customer": {
            "email": user.email or f"{user.username}@users.safarichap.co.tz",
            "phonenumber": user.phone_number or "",
            "name": user.full_name or "SafariChap traveller",
        },
        "customizations": {"title": "SafariChap", "description": title},
    })
    link = data.get('link')
    if not link:
        raise ProviderError("Flutterwave checkout link missing")
    return link


def verify_by_reference(order_reference: str) -> dict | None:
    try:
        return _request('GET', '/transactions/verify_by_reference', params={"tx_ref": order_reference})
    except ProviderError:
        return None


def refund(transaction_id: str, amount: int, currency: str) -> dict:
    return _request('POST', f'/transactions/{transaction_id}/refund', json={"amount": _major(amount, currency)})


def verify_webhook(request) -> bool:
    expected = settings.FLUTTERWAVE_WEBHOOK_HASH
    if not expected:
        logger.error("FLUTTERWAVE_WEBHOOK_HASH is not set; rejecting webhook.")
        return False
    return hmac.compare_digest(request.headers.get('verif-hash', ''), expected)
