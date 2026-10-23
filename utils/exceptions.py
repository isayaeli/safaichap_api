from rest_framework import status
from rest_framework.exceptions import APIException


class BadRequest(APIException):
    """400 with a friendly {"detail": "..."} the app shows verbatim."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Something about this request isn't right."
    default_code = 'bad_request'


class Conflict(APIException):
    """409: the object is in a state that doesn't allow this action."""
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This action isn't allowed right now."
    default_code = 'conflict'


class ProviderError(Exception):
    """A payment provider call failed. `user_message` is safe to show to users."""

    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or "We couldn't reach the payment provider. Please try again."


class ScheduleValidationError(Exception):
    """Raised by the schedule rules; the message is shown to users."""
