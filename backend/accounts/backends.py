import re

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


def _normalize_phone(raw: str) -> str:
    """Same shorthand the operator-enrollment form uses on the frontend
    (AddParentForm.tsx's normalizePhone): a bare 10-digit number is assumed
    US/+1 - this is a single-market Miami gym, not a general phone input.
    Anything already starting with "+" is left alone."""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        return digits
    if len(digits) == 10:
        return f"+1{digits}"
    return digits


class FlexibleLoginBackend(ModelBackend):
    """Login by username, email, or phone number - whichever the submitted
    identifier matches. accounts.models.User.USERNAME_FIELD is still
    'username' (SimpleJWT/Django auth() call this kwarg "username"
    regardless), but a parent only ever knows the phone number they were
    enrolled with (EnrollParentView sets username = that phone), and some
    staff accounts are created with an email as their identifier instead -
    neither should be forced through a literal Django "username".
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        query = Q(username__iexact=username) | Q(email__iexact=username)

        # _normalize_phone("juan") is "" (every character gets stripped as
        # non-digit), and User.phone_number is blank (not null) when unset -
        # Q(phone_number="") would then match every phone-less account and
        # .first() picks an arbitrary one, silently authenticating as the
        # wrong user. Only add the phone clause once normalization actually
        # produced something phone-shaped.
        normalized_phone = _normalize_phone(username)
        if normalized_phone.startswith("+"):
            query |= Q(phone_number=normalized_phone)

        user = User.objects.filter(query).first()
        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
