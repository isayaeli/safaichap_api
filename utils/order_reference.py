import secrets
import string
import time
import uuid

_ALPHABET = string.ascii_uppercase + string.digits


def generate_order_reference(prefix: str = "SC") -> str:
    """
    Generates a unique, ClickPesa-safe (alphanumeric) order reference.
    Format: SCRF20261018A1B2C3D4
    """
    date_part = time.strftime("%Y%m%d")
    unique_part = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{date_part}{unique_part}"


def random_code(length: int = 6) -> str:
    return ''.join(secrets.choice(_ALPHABET) for _ in range(length))


def confirmation_code() -> str:
    """Booking confirmation code, e.g. SC-7F3K2Q."""
    return f"SC-{random_code(6)}"


def receipt_number() -> str:
    """Payment receipt number, e.g. SC-RCPT-7F3K2Q9A."""
    return f"SC-RCPT-{random_code(8)}"
