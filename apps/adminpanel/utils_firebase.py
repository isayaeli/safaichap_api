"""Firebase user management for staff invites (firebase_admin must be initialised)."""
from firebase_admin import auth

from utils.exceptions import BadRequest


def get_or_create_firebase_user(email: str, display_name: str | None = None) -> str:
    """Returns the Firebase uid for `email`, creating a password-less user if needed."""
    try:
        return auth.get_user_by_email(email).uid
    except auth.UserNotFoundError:
        pass
    except ValueError:
        raise BadRequest("Firebase isn't configured on the server.")
    try:
        return auth.create_user(email=email, display_name=display_name or None, email_verified=False).uid
    except Exception:
        raise BadRequest("We couldn't create the sign-in account for this email.")


def password_setup_link(email: str) -> str | None:
    """A Firebase password-reset link the new staff member uses to set their password."""
    try:
        return auth.generate_password_reset_link(email)
    except Exception:
        return None
