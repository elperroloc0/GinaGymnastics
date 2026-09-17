from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")
router.register("schedules", views.ChildScheduleViewSet, basename="childschedule")
router.register("operators", views.OperatorViewSet, basename="operator")
router.register("parents", views.ParentViewSet, basename="parent")

urlpatterns = router.urls + [
    path("enroll-parent/", views.EnrollParentView.as_view(), name="enroll-parent"),
    path("set-password/", views.SetPasswordView.as_view(), name="set-password"),
    path("set-password/<str:token>/", views.InviteInfoView.as_view(), name="set-password-invite-info"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="forgot-password"),
    path("forgot-password/verify/", views.VerifyResetCodeView.as_view(), name="forgot-password-verify"),
    path("me/", views.MeView.as_view(), name="me"),
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
]

