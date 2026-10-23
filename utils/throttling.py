from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import ScopedRateThrottle


class ScopedWriteRateThrottle(ScopedRateThrottle):
    """
    `throttle_scope` limits only writes, so a view like GET/POST /api/goals/
    can cap goal creation without also capping the list. Reads still count
    toward the global per-user rate.
    """

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)
