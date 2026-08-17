
from django.db import models


# Create your models here.
class Van(models.Model):
    name = models.CharField(max_length=20, unique=True, help_text="Van plate number")
    tracker_imei = models.CharField(max_length=20, unique=True, help_text="Tracker's IMEI number")


    def __str__(self):
        return self.name


class GeoFence(models.Model):
    class LocationTypes(models.TextChoices):
        SCHOOL = "SCHOOL", "School"
        GINAS_GYM = "GYM", "Gina's Gymnastics"

    name = models.CharField(max_length=32)

    location_type = models.CharField(max_length=32, choices=LocationTypes.choices, default=LocationTypes.SCHOOL)

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius = models.PositiveIntegerField(help_text="meters")
    traccar_id = models.IntegerField(unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Route(models.Model):
    van = models.ForeignKey(Van, on_delete=models.PROTECT, related_name="routes")
    origin = models.ForeignKey(GeoFence, on_delete=models.PROTECT, related_name="routes_from")
    destination = models.ForeignKey(GeoFence, on_delete=models.PROTECT, related_name="routes_to")

    def __str__(self) -> str:
        return f"{self.van}: From {self.origin} to {self.destination}"
