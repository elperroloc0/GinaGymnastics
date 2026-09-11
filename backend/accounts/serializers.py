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
