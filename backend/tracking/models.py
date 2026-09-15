from django.db import models
from fleet.models import GeoFence, Van


class ArrivalEvent(models.Model):
    class ArrivalType(models.TextChoices):
        ENTER = "in", "Arrived"
        EXIT = "out", "Left"

    van = models.ForeignKey(Van, on_delete=models.PROTECT)
    geo_fence = models.ForeignKey(GeoFence, on_delete=models.PROTECT)
    arrival_type = models.CharField(max_length=12, choices=ArrivalType.choices)
    time = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.van} is {self.arrival_type} {self.geo_fence}"


class Position(models.Model):
    """One GPS fix from a van's tracker.

    Positions are persisted for two reasons the live broadcast can't cover:
    a socket that opens mid-ride is seeded with the last known fix instead of
    showing an empty map until the next ping, and the console can replay a day.

    `device_time` is the tracker's own clock, not server receipt time. Staleness
    has to be measured against it: a tracker that went quiet and then delivers a
    backlog would look perfectly healthy by receipt time.
    """

    # CASCADE, unlike ArrivalEvent's PROTECT: an arrival is a business record,
    # this is telemetry. ArrivalEvent already blocks deleting a van that ran.
    van = models.ForeignKey(Van, on_delete=models.CASCADE, related_name="positions")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    # Course over ground in degrees (0-360, 0=north), as reported by the
    # tracker's GPS chip - not computed from consecutive fixes here. Null
    # when the device didn't report one (rare) rather than defaulting to 0,
    # which would otherwise look like a real "facing north" reading.
    course = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    device_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Every read is "latest first, for one van".
        indexes = [models.Index(fields=["van", "-device_time"])]
        get_latest_by = "device_time"

    def __str__(self) -> str:
        return f"{self.van} at {self.device_time:%Y-%m-%d %H:%M:%S}"
