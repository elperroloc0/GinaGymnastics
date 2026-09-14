from django.contrib.auth.password_validation import validate_password
from fleet.models import Route
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Child, ChildSchedule


class ChildScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChildSchedule
        fields = ["id", "child", "weekday", "pickup_hour"]


class ChildSerializer(serializers.ModelSerializer):
    schedule = ChildScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Child
        fields = ["id", "name", "parent", "route", "schedule"]


class RoleTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds role/identity claims the frontend decodes client-side to pick
    which UI shell to render (parent app vs. operator console).

    This is a UX/routing convenience only, never a security boundary - every
    endpoint still enforces its own permission (IsOperatorOrReadOnly) and
    queryset scoping server-side regardless of what these claims say.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["is_superuser"] = user.is_superuser
        token["first_name"] = user.first_name
        return token


class EnrollParentSerializer(serializers.Serializer):
    """Input for EnrollParentView - operator-only, creates (or reuses) a
    parent account plus one enrolled child with a weekly schedule."""

    parent_phone = PhoneNumberField()
    parent_name = serializers.CharField(required=False, allow_blank=True, default='')
    child_name = serializers.CharField(max_length=150)
    route = serializers.PrimaryKeyRelatedField(queryset=Route.objects.all())
    weekdays = serializers.ListField(
        child=serializers.ChoiceField(choices=ChildSchedule.Weekday.choices),
        allow_empty=False,
    )
    pickup_hour = serializers.TimeField()


class SetPasswordSerializer(serializers.Serializer):
    """Input for SetPasswordView - the public endpoint a ParentInvite link
    lands on. Not a ModelSerializer: there is no single model instance being
    read or written here, just two independent fields to validate."""

    token = serializers.CharField()
    password = serializers.CharField()

    def validate_password(self, value):
        validate_password(value)
        return value
