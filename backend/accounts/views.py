from accounts.permission import IsOperator, IsOperatorOrReadOnly
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from notifications.tasks import debug_sms
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Child, ChildSchedule, ParentInvite, User
from .serializers import (
    ChildScheduleSerializer,
    ChildSerializer,
    EnrollParentSerializer,
    RoleTokenObtainPairSerializer,
    SetPasswordSerializer,
)

# Create your views here.

class ChildViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:#type:ignore
            return Child.objects.all()

        return Child.objects.filter(parent=user)

    serializer_class = ChildSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]


class ChildScheduleViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser: #type: ignore
            return ChildSchedule.objects.all()

        return ChildSchedule.objects.filter(child__parent=user)

    serializer_class = ChildScheduleSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]


class RoleTokenObtainPairView(TokenObtainPairView):
    serializer_class = RoleTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class EnrollParentView(APIView):
    """Operator-only: creates (or reuses) a parent account and enrolls one
    child under it in a single call. A newly created parent gets an unusable
    password and a texted ParentInvite link to set their own; an existing
    parent (same phone, already has a password) just gets the new child
    added, no new text - see accounts/models.py's ParentInvite doc comment.

    Real authorization is IsOperator below, not the JWT role claim the
    frontend also reads for UI branching - see
    RoleTokenObtainPairSerializer's own doc comment.
    """

    permission_classes = [permissions.IsAuthenticated, IsOperator]

    def post(self, request):
        serializer = EnrollParentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        phone = str(data["parent_phone"])
        parent = User.objects.filter(phone_number=phone, role=User.Roles.PARENT).first()
        invited = parent is None

        with transaction.atomic():
            if parent is None:
                parent = User(
                    username=phone,
                    role=User.Roles.PARENT,
                    phone_number=phone,
                    first_name=data["parent_name"],
                )
                # No password yet - set_password() only ever runs from
                # SetPasswordView, once the parent follows their invite link.
                parent.set_unusable_password()
                parent.save()

            child = Child.objects.create(name=data["child_name"], parent=parent, route=data["route"])
            for weekday in data["weekdays"]:
                ChildSchedule.objects.create(child=child, weekday=weekday, pickup_hour=data["pickup_hour"])

            if invited:
                invite = ParentInvite.objects.create(user=parent)

        if invited:
            # Sent after the transaction commits (delay_on_commit, called
            # outside the `with` block above) - never text a link for rows
            # that could still be rolled back.
            link = request.build_absolute_uri(f"/set-password/{invite.token}")
            message = (
                f"Gina's Gymnastics: {data['child_name']} is enrolled for van rides. "
                f"Set up your Ride Tracker account: {link}"
            )
            debug_sms.delay_on_commit(phone, message)

        return Response({"child": ChildSerializer(child).data, "invited": invited}, status=status.HTTP_201_CREATED)


class SetPasswordView(APIView):
    """Public, token-gated: where a ParentInvite link lands. Not behind auth -
    the token itself is the credential, single-use and time-limited
    (ParentInvite.TTL). Returns a token pair on success so the parent lands
    signed in, without typing the password they just chose a second time."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "set_password"

    def post(self, request):
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            invite = ParentInvite.objects.select_related("user").get(token=serializer.validated_data["token"])
        except ParentInvite.DoesNotExist:
            return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

        if not invite.is_valid():
            return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

        user = invite.user
        user.set_password(serializer.validated_data["password"])
        user.save()
        invite.used_at = timezone.now()
        invite.save(update_fields=["used_at"])

        token = RoleTokenObtainPairSerializer.get_token(user)
        return Response({"access": str(token.access_token), "refresh": str(token)})
