from django.contrib.auth.password_validation import validate_password
from fleet.models import Route
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Child, ChildSchedule, User


class ChildScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChildSchedule
        fields = ["id", "child", "weekday", "pickup_hour"]


class ChildSerializer(serializers.ModelSerializer):
    schedule = ChildScheduleSerializer(many=True, read_only=True)
    parent_name = serializers.CharField(source="parent.first_name", read_only=True)
    parent_phone_number = serializers.CharField(source="parent.phone_number", read_only=True)

    class Meta:
        model = Child
        fields = ["id", "name", "parent", "parent_name", "parent_phone_number", "route", "schedule"]


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


class OperatorSerializer(serializers.ModelSerializer):
    """Input/output for OperatorViewSet - operator-only account creation and
    listing. `password` is write-only: it's set on the new account here, not
    via a texted invite link like ParentInvite (that mechanism is
    parent-specific)."""

    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "email", "phone_number", "is_active", "password"]
        read_only_fields = ["id", "is_active"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(role=User.Roles.OPERATOR, **validated_data)
        user.set_password(password)
        user.save()
        return user


class ParentSerializer(serializers.ModelSerializer):
    """Operator-only view/edit of a parent account. Supports PATCH, unlike
    OperatorSerializer - phone_number/username stay in lockstep (see update()),
    mirroring the invariant EnrollParentView sets at creation. No password
    field anywhere: a parent's password is never operator-writable or
    -readable, only self-service via SetPasswordView/ParentInvite."""

    children = ChildSerializer(many=True, read_only=True)
    is_registered = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "email", "phone_number", "is_active", "is_registered", "children"]
        read_only_fields = ["id", "username", "is_active", "is_registered", "children"]

    def get_is_registered(self, obj):
        # False until the parent actually follows their invite link and sets a
        # real password (SetPasswordView) - set_unusable_password() at
        # creation (EnrollParentView) is what makes this False for a new row.
        return obj.has_usable_password()

    def validate_phone_number(self, value):
        if User.objects.exclude(pk=self.instance.pk).filter(username=str(value)).exists():
            raise serializers.ValidationError("Another account already uses this phone number.")
        return value

    def update(self, instance, validated_data):
        if "phone_number" in validated_data:
            validated_data["username"] = str(validated_data["phone_number"])
        return super().update(instance, validated_data)


class SetPasswordSerializer(serializers.Serializer):
    """Input for SetPasswordView - the public endpoint a ParentInvite link
    lands on. Not a ModelSerializer: there is no single model instance being
    read or written here, just two independent fields to validate."""

    token = serializers.CharField()
    password = serializers.CharField()

    def validate_password(self, value):
        validate_password(value)
        return value
