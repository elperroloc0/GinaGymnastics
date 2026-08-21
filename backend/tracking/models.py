from django.db import models
from fleet.models import GeoFence, Van


# Create your models here.
class ArrivalEvent(models.Model):
    class ArrivalType(models.TextChoices):
        ENTER = "in", "Arrived"
        EXIT = "out", "Left"

    van = models.ForeignKey(Van, on_delete=models.PROTECT)
    geo_fence = models.ForeignKey(GeoFence, on_delete=models.PROTECT)
    arrival_type = models.CharField(max_length=12, choices=ArrivalType.choices)
    time = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.van} is {self.arrival_type} | Location: {self.geo_fence}"
