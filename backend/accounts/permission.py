from rest_framework import permissions

from .models import User


class IsOperatorOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        return User.Roles.OPERATOR == request.user.role or request.user.is_superuser
