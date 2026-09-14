from rest_framework import permissions

from .models import User


class IsOperatorOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        return User.Roles.OPERATOR == request.user.role or request.user.is_superuser


class IsOperator(permissions.BasePermission):
    """Operator-only, no read-only carve-out - for endpoints a parent should
    never be able to call at all, like enrolling another parent."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.role == User.Roles.OPERATOR or user.is_superuser)
        )
