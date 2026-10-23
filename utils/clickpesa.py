import hmac
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from utils.exceptions import ProviderError

logger = logging.getLogger(__name__)

TOKEN_KEY = "clickpesa:jwt"
LOCK_KEY = "clickpesa:jwt:lock"
TOKEN_TTL = 55 * 60  # ClickPesa tokens live 1 hour; refresh a little early
LOCK_TTL = 30        # seconds
TIMEOUT = 20

SUCCESS_STATUSES = {'SUCCESS', 'SETTLED'}
FAILED_STATUSES = {'FAILED', 'REVERSED', 'REFUNDED'}


def _url(path: str) -> str:
    return f"{settings.CLICKPESA_BASE_URL}{path}"


def get_clickpesa_jwt_token():
    """
    Returns a valid ClickPesa JWT token.
    Uses Redis caching + locking to avoid race conditions.
    """
    token = cache.get(TOKEN_KEY)
    if token:
        return token

    lock = cache.lock(LOCK_KEY, timeout=LOCK_TTL) if hasattr(cache, 'lock') else None
    if lock is not None and not lock.acquire(blocking=True, blocking_timeout=LOCK_TTL):
        raise ProviderError("Could not acquire ClickPesa token lock")

    try:
        token = cache.get(TOKEN_KEY)
        if token:
            return token

        response = requests.post(
            settings.CLICKPESA_TOKEN_URL,
            headers={
                "api-key": settings.CLICKPESA_API_KEY,
                "client-id": settings.CLICKPESA_CLIENT_ID,
            },
            timeout=15,
        )
        if response.status_code != 200:
            raise ProviderError(f"ClickPesa token generation failed with {response.status_code}")

        data = response.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            raise ProviderError("JWT token missing from ClickPesa response")

        cache.set(TOKEN_KEY, token, timeout=TOKEN_TTL)
        return token
    finally:
        if lock is not None:
            lock.release()


def _headers():
    # ClickPesa returns the token with its "Bearer " prefix already applied.
    return {
        "Authorization": get_clickpesa_jwt_token().strip(),
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> dict:
    try:
        response = requests.post(_url(path), json=payload, headers=_headers(), timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        raise ProviderError("ClickPesa timeout", "Your mobile money provider took too long to respond. Please try again.")
    except requests.exceptions.RequestException as e:
        raise ProviderError(f"ClickPesa request failed: {type(e).__name__}")

    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code not in (200, 201):
        logger.warning("ClickPesa %s returned %s: %s", path, response.status_code, body)
        raise ProviderError(
            f"ClickPesa {path} returned {response.status_code}",
            "We couldn't start the payment on this number. Check the number and try again.",
        )
    return body


def initiate_ussd_push(order_reference: str, amount: int, phone_number: str) -> dict:
    """Previews then sends a USSD push to the customer's phone (amount in TZS)."""
    payload = {
        "amount": str(amount),
        "currency": "TZS",
        "orderReference": order_reference,
        "phoneNumber": phone_number,
    }
    _post("/payments/preview-ussd-push-request", payload)
    return _post("/payments/initiate-ussd-push-request", payload)


def query_payment_status(order_reference: str) -> dict | None:
    """Returns the latest ClickPesa payment record for the reference, or None."""
    try:
        response = requests.get(_url(f"/payments/{order_reference}"), headers=_headers(), timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise ProviderError(f"ClickPesa status query failed: {type(e).__name__}")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ProviderError(f"ClickPesa status query returned {response.status_code}")
    data = response.json()
    if isinstance(data, list):
        return data[0] if data else None
    return data


def create_mobile_payout(order_reference: str, amount: int, phone_number: str) -> dict:
    """Previews then creates a mobile money payout (used for refunds)."""
    payload = {
        "amount": amount,
        "currency": "TZS",
        "orderReference": order_reference,
        "phoneNumber": phone_number,
    }
    _post("/payouts/preview-mobile-money-payout", payload)
    return _post("/payouts/create-mobile-money-payout", payload)


def verify_webhook(request) -> bool:
    """
    ClickPesa webhooks are verified with a shared secret we put in the callback
    URL registered in the ClickPesa dashboard (?secret=...). Unverified calls
    are rejected.
    """
    expected = settings.CLICKPESA_WEBHOOK_SECRET
    if not expected:
        logger.error("CLICK_PESA_WEBHOOK_SECRET is not set; rejecting webhook.")
        return False
    provided = request.query_params.get('secret') or request.headers.get('X-Webhook-Secret') or ''
    return hmac.compare_digest(provided, expected)
