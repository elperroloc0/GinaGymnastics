"""Utility functions for tracking's live-map access logic."""
from datetime import timedelta

from django.utils import timezone

# How long an active ride is trusted without a destination-arrival event
# turning it off. Self-healing safety net: if that webhook is ever lost,
# a parent doesn't keep map access forever.
ACTIVE_RIDE_MAX_DURATION = timedelta(hours=6)


def is_ride_active(child) -> bool:
    """Whether `child`'s ride should currently grant live-map access."""
    if not child.active_ride:
        return False

    # active_ride=True with no start time (row set by hand in admin, or predating
    # the active_ride_start column) can't be aged out, so don't trust it.
    if child.active_ride_start is None:
        return False

    if timezone.now() > child.active_ride_start + ACTIVE_RIDE_MAX_DURATION:
        return False

    return True
