from accounts.permission import IsOperator, IsOperatorOrReadOnly
from django.conf import settings
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from notifications.tasks import debug_sms
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Child, ChildSchedule, ParentInvite, User
from .serializers import (
    ChildScheduleSerializer,
    ChildSerializer,
    EnrollParentSerializer,
    OperatorSerializer,
    ParentSerializer,
    RoleTokenObtainPairSerializer,
    SetPasswordSerializer,
)

# Create your views here.


def _set_password_link(token) -> str:
    """Builds the set-password link texted to a parent (enrollment invite,
    resend-invite). NOT request.build_absolute_uri() - that resolves against
    this API's own domain, but /set-password/:token is a frontend (Vercel)
    route Django doesn't serve at all, so that link 404s. The frontend's
    origin is CORS_ALLOWED_ORIGINS (settings.py) - same value, no second
    env var - same reasoning as tracking/views.py's arrival_webhook link."""
    frontend_url = settings.CORS_ALLOWED_ORIGINS[0] if settings.CORS_ALLOWED_ORIGINS else ""
    return f"{frontend_url}/set-password/{token}"

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


class OperatorViewSet(viewsets.ModelViewSet):
    """Operator-only account creation/listing for other operators - parent
    accounts go through EnrollParentView instead, this never touches those.
    No update/delete: deactivate() below is the only way to remove access,
    keeping login history and FK references (e.g. audit trails) intact.
    """

    http_method_names = ["get", "post", "head", "options"]
    serializer_class = OperatorSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperator]

    def get_queryset(self):
        return User.objects.filter(role=User.Roles.OPERATOR, is_superuser=False)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        operator = self.get_object()
        operator.is_active = False
        operator.save(update_fields=["is_active"])
        return Response(OperatorSerializer(operator).data)


class ParentViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Operator-only view/edit/deactivate for parent accounts. No create or
    delete mixin on purpose - parents are still only created via
    EnrollParentView, and deactivate() is the only way to remove access
    (ModelViewSet would also need http_method_names to exclude "post" to block
    create, but that would break the POST-based @action endpoints below too -
    leaving CreateModelMixin/DestroyModelMixin out entirely is the clean fix)."""

    serializer_class = ParentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperator]

    def get_queryset(self):
        return User.objects.filter(role=User.Roles.PARENT).prefetch_related("children__schedule")

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        parent = self.get_object()
        parent.is_active = False
        parent.save(update_fields=["is_active"])
        return Response(ParentSerializer(parent).data)

    @action(detail=True, methods=["post"])
    def resend_invite(self, request, pk=None):
        parent = self.get_object()
        # phone_number is blank=True on the model - a handful of real rows
        # predate EnrollParentView (which always requires one) and have none.
        # Without this check we'd create a ParentInvite nobody can ever use
        # and hand Twilio an empty "to" number.
        if not parent.phone_number:
            return Response({"detail": "This parent has no phone number on file - add one before sending a link."}, status=400)
        invite = ParentInvite.objects.create(user=parent)
        link = _set_password_link(invite.token)
        debug_sms.delay_on_commit(str(parent.phone_number), f"Gina's Gymnastics: reset your Ride Tracker access here: {link}")
        return Response(ParentSerializer(parent).data)


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
            link = _set_password_link(invite.token)
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
