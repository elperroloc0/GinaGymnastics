from django.contrib.auth.models import AbstractUser
from django.db import models
from fleet.models import Route
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
    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name='children')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f'{self.name} -- {self.route}'


class ChildSchedule(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name='schedule')
    weekday = models.IntegerField(choices=Weekday.choices)
    pickup_hour = models.TimeField()

    class Meta:
        unique_together = ('child', 'weekday')
        ordering = ['weekday']

    def __str__(self) -> str:
        return f'{self.child} -- {self.get_weekday_display()} {self.pickup_hour}' # type: ignore
