
from django.contrib.auth.models import AbstractUser
from django.db import models
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
