
from encodings.punycode import T
from pyexpat import model

from django.contrib.auth.models import AbstractUser
from django.db import models
from fleet.models import GeoFence
from phonenumber_field.modelfields import PhoneNumberField


# Create your models here
class User(AbstractUser):
    class Roles(models.TextChoices):
        PARENT = 'PARENT', 'Parent'
        OPERATOR = 'OPERATOR', 'Operator'

    role = models.CharField(
        max_length=20,
        choices=Roles.choices,
        default=Roles.PARENT
    )
    # an optional phone number for parents notifications
    phone_number = PhoneNumberField(blank=True)


class Child(models.Model):
    class Meta:
        verbose_name_plural = "children"
    name = models.CharField("First and Last name", max_length=150)
    parent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='children')
    school = models.ForeignKey(GeoFence, on_delete=models.PROTECT, verbose_name="School", related_name='children')
    pickup_hour = models.TimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f'{self.name} -- {self.school}'
