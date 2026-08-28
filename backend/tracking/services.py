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

    if timezone.now() > child.active_ride_start + ACTIVE_RIDE_MAX_DURATION:
        return False

    return True
