
from django.core.exceptions import ValidationError
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

    def clean(self):
            if self.origin.location_type == self.destination.location_type:
                raise ValidationError("Origin and destination must be diferent.")

            elif self.origin.location_type != GeoFence.LocationTypes.SCHOOL:
                raise ValidationError("Origin must be an school.")

            elif self.destination.location_type != GeoFence.LocationTypes.GINAS_GYM:
                raise ValidationError("Destination must be a gym.")

    def save(self,*args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

