import hmac
import secrets

from accounts.permission import IsOperator, IsOperatorOrReadOnly
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from notifications.tasks import debug_sms
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Child, ChildSchedule, ParentInvite, User
from .serializers import (
    ChangePasswordSerializer,
    ChildScheduleSerializer,
    ChildSerializer,
    EnrollParentSerializer,
    ForgotPasswordSerializer,
    InviteInfoSerializer,
    MeSerializer,
    OperatorSerializer,
    ParentSerializer,
    RoleTokenObtainPairSerializer,
    SetPasswordSerializer,
    VerifyResetCodeSerializer,
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


def _get_valid_invite(token: str) -> ParentInvite | None:
    """Looks up a ParentInvite by token and returns it only if still valid
    (unused, within TTL). Shared by InviteInfoView and SetPasswordView so
    both agree on what "valid" means and return the same generic error."""
    try:
        invite = ParentInvite.objects.select_related("user").get(token=token)
    except ParentInvite.DoesNotExist:
        return None
    return invite if invite.is_valid() else None


def _generate_parent_username(first_name: str) -> str:
    """Base username slugified from the parent's name, deduplicated with a
    numeric suffix on collision. Generated once at creation and never
    resynced afterward - phone_number (not this) is the actual login
    credential a parent types in, matched directly by FlexibleLoginBackend
    regardless of what username holds. This exists so Django admin's user
    list shows a name-shaped handle instead of a phone number sitting in a
    field literally called "username"."""
    base = slugify(first_name) or "parent"
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


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
                    username=_generate_parent_username(data["parent_name"]),
                    role=User.Roles.PARENT,
                    phone_number=phone,
                    first_name=data["parent_name"],
                    email=data["email"],
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


class InviteInfoView(APIView):
    """Public, token-gated: GET counterpart to SetPasswordView, used by the
    set-password page to show whose account it's activating - name and the
    phone number they'll need to remember as their login - before they type
    anything. Same validity rule as SetPasswordView (_get_valid_invite),
    so a link that's expired or already used shows the same error either
    way instead of leaking "this token exists but is spent"."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "set_password"

    def get(self, request, token):
        invite = _get_valid_invite(token)
        if invite is None:
            return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InviteInfoSerializer(invite.user).data)


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

        invite = _get_valid_invite(serializer.validated_data["token"])
        if invite is None:
            return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

        user = invite.user
        user.set_password(serializer.validated_data["password"])
        user.save()
        invite.used_at = timezone.now()
        invite.save(update_fields=["used_at"])

        token = RoleTokenObtainPairSerializer.get_token(user)
        return Response({"access": str(token.access_token), "refresh": str(token)})


# --- Self-service password reset: phone -> texted code -> ParentInvite ---
#
# Two-step by design, not one. A bare phone number is not proof of anything
# (anyone can type in anyone else's number) - RESET_CODE_TTL_SECONDS below is
# how long a code stays valid for VerifyResetCodeView to actually prove the
# caller has the phone, *before* a ParentInvite token is ever minted. Once
# verified, the rest of the flow (InviteInfoView, SetPasswordView) is the
# exact same one an operator-sent invite link lands on - this only changes
# how the invite gets created, not what it is once it exists.
RESET_CODE_TTL_SECONDS = 600  # 10 minutes
RESET_CODE_MAX_VERIFY_ATTEMPTS = 5
RESET_CODE_MAX_SENDS_PER_PHONE_PER_HOUR = 5


def _reset_code_key(phone: str) -> str:
    return f"password_reset_code:{phone}"


def _reset_code_attempts_key(phone: str) -> str:
    return f"password_reset_attempts:{phone}"


def _reset_code_send_count_key(phone: str) -> str:
    return f"password_reset_sends:{phone}"


class ForgotPasswordView(APIView):
    """Public, self-service password reset for a parent who forgot theirs
    and doesn't want to call the gym - step 1 of 2, texts a short code
    rather than a link (see VerifyResetCodeView for step 2 and why).

    The response is identical whether or not the phone number actually
    matches an account: a public endpoint that answered differently for
    "this number has an account with a child" vs. "it doesn't" would let
    anyone probe which phone numbers are enrolled here. Same reasoning is
    why a phone number that's already had RESET_CODE_MAX_SENDS_PER_PHONE_PER_HOUR
    codes sent this hour gets this same response too, silently - without
    that cap, ScopedRateThrottle alone (keyed by IP) doesn't stop someone
    with access to several IPs from repeatedly texting a stranger's phone."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "forgot_password"

    GENERIC_RESPONSE = {"detail": "If an account exists for that number, we've texted a reset code."}

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = str(serializer.validated_data["phone_number"])

        parent = User.objects.filter(phone_number=phone, role=User.Roles.PARENT).first()
        if parent is not None:
            send_count = cache.get(_reset_code_send_count_key(phone), 0)
            if send_count < RESET_CODE_MAX_SENDS_PER_PHONE_PER_HOUR:
                code = f"{secrets.randbelow(1_000_000):06d}"
                cache.set(_reset_code_key(phone), code, timeout=RESET_CODE_TTL_SECONDS)
                # A fresh code means a fresh attempt budget against it.
                cache.delete(_reset_code_attempts_key(phone))
                cache.set(_reset_code_send_count_key(phone), send_count + 1, timeout=3600)
                debug_sms.delay_on_commit(
                    phone, f"Gina's Gymnastics: your Ride Tracker reset code is {code}. It expires in 10 minutes."
                )

        return Response(self.GENERIC_RESPONSE)


class VerifyResetCodeView(APIView):
    """Step 2: exchanges the code ForgotPasswordView just texted for a
    normal ParentInvite token, handing off into the exact same
    InviteInfoView/SetPasswordView flow an operator-sent invite link lands
    on. This view's only job is proving the caller actually received that
    code - constant-time compare (hmac.compare_digest) so response timing
    can't leak how much of a guess was right, single-use (deleted on a
    correct guess), and a hard cap on wrong guesses (RESET_CODE_MAX_VERIFY_ATTEMPTS)
    so the code's 1-in-a-million space can't just be brute-forced within
    its 10-minute window."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_reset_code"

    INVALID_RESPONSE = {"detail": "Incorrect or expired code."}
    TOO_MANY_ATTEMPTS_RESPONSE = {"detail": "Too many attempts. Request a new code."}

    def post(self, request):
        serializer = VerifyResetCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = str(serializer.validated_data["phone_number"])
        submitted_code = serializer.validated_data["code"]

        attempts = cache.get(_reset_code_attempts_key(phone), 0)
        if attempts >= RESET_CODE_MAX_VERIFY_ATTEMPTS:
            return Response(self.TOO_MANY_ATTEMPTS_RESPONSE, status=status.HTTP_400_BAD_REQUEST)

        stored_code = cache.get(_reset_code_key(phone))
        if stored_code is None or not hmac.compare_digest(stored_code, submitted_code):
            cache.set(_reset_code_attempts_key(phone), attempts + 1, timeout=RESET_CODE_TTL_SECONDS)
            return Response(self.INVALID_RESPONSE, status=status.HTTP_400_BAD_REQUEST)

        # Correct - single use, same guarantee a ParentInvite token has.
        cache.delete(_reset_code_key(phone))
        cache.delete(_reset_code_attempts_key(phone))

        parent = User.objects.filter(phone_number=phone, role=User.Roles.PARENT).first()
        if parent is None:
            # The matching account was deleted/changed between send and
            # verify - vanishingly rare, but the code genuinely matched what
            # was stored, so this is a real inconsistency, not a guess.
            return Response(self.INVALID_RESPONSE, status=status.HTTP_400_BAD_REQUEST)

        invite = ParentInvite.objects.create(user=parent)
        return Response({"token": invite.token})


class MeView(APIView):
    """Self-service profile for whoever is signed in - GET to read it, PATCH
    to edit the narrow slice MeSerializer allows (currently just email).
    Not role-restricted, though a parent's own account screen is the only
    place this is used today - see ParentAccount, a later step."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordView(APIView):
    """Self-service password change for a signed-in user who still knows
    their current password - SetPasswordView (a ParentInvite token) is the
    path for someone who doesn't."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not request.user.check_password(serializer.validated_data["current_password"]):
            return Response({"detail": "Current password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
