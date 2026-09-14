from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")
router.register("schedules", views.ChildScheduleViewSet, basename="childschedule")

urlpatterns = router.urls + [
    path("enroll-parent/", views.EnrollParentView.as_view(), name="enroll-parent"),
    path("set-password/", views.SetPasswordView.as_view(), name="set-password"),
]

