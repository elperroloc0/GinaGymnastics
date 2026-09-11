import base64
import json

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from fleet.models import GeoFence, Route, Van
from rest_framework.test import APIClient

from .models import Child, User

JWT_AUTH_CLASS = "rest_framework_simplejwt.authentication.JWTAuthentication"

# /api/token/ is always throttled (accounts/views.py's RoleTokenObtainPairView),
# and throttling reads/writes through the default cache - django_redis,
# pointed at a real Redis in settings.py. Any test that logs in needs an
# in-memory cache instead, so it doesn't require a live Redis, matching
# tracking/tests.py's own pattern for the same reason.
locmem_cache = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)


def _decode_jwt_payload(token):
    # Test-only decode (no signature check) - just inspecting the claims we
    # put there, the same way the frontend's src/auth/jwt.ts does for
    # UI-branching purposes only.
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


@locmem_cache
class DebugModeAuthTest(TestCase):
    """Regression coverage for a real bug: settings.py used to REPLACE
    DEFAULT_AUTHENTICATION_CLASSES with Basic/Session whenever DEBUG=True,
    instead of adding to JWTAuthentication. Net effect: a real
    `Authorization: Bearer <token>` header was silently ignored on every
    local dev run (backend/.env ships DEBUG=True), and every IsAuthenticated
    endpoint 401'd for the frontend's actual request pattern.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="parent1", password="pw12345!", role=User.Roles.PARENT
        )
        van = Van.objects.create(name="VAN-1", tracker_imei="IMEI0001")
        school = GeoFence.objects.create(
            name="Test School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.7, longitude=-80.4, radius=50, traccar_id=101,
        )
        gym = GeoFence.objects.create(
            name="Test Gym", location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.8, longitude=-80.5, radius=50, traccar_id=102,
        )
        route = Route.objects.create(van=van, origin=school, destination=gym)
        self.child = Child.objects.create(name="Test Child", parent=self.user, route=route)

    def test_jwt_authentication_class_always_present(self):
        # Direct check of the invariant the bug violated: settings.DEBUG's
        # value at process start bakes DEFAULT_AUTHENTICATION_CLASSES into
        # settings.REST_FRAMEWORK once at import time, so this can't be
        # exercised by toggling DEBUG at test-run time (override_settings
        # would not retroactively recompute it) - assert the actual invariant
        # (JWT is never dropped, regardless of what DEBUG happened to be at
        # startup) instead of simulating a DEBUG flip that wouldn't do anything.
        classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
        self.assertIn(JWT_AUTH_CLASS, classes)

    def test_bearer_token_authenticates_real_request(self):
        # End-to-end: this is the exact pattern that silently 401'd under the
        # bug - a real access token obtained from /api/token/, sent as a
        # real Authorization header, against a real IsAuthenticated view.
        token_response = self.client.post(
            "/api/token/",
            {"username": "parent1", "password": "pw12345!"},
            content_type="application/json",
        )
        self.assertEqual(token_response.status_code, 200)
        access = token_response.json()["access"]

        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = api_client.get("/api/children/")

        self.assertEqual(response.status_code, 200)
        names = [c["name"] for c in response.json()]
        self.assertIn(self.child.name, names)



@locmem_cache
class RoleTokenClaimTest(TestCase):
    def setUp(self):
        # The login throttle's history lives in the cache, not the DB, so it
        # isn't reset by TestCase's per-test transaction rollback - clear it
        # explicitly so one test's login attempts can't throttle the next.
        cache.clear()
        self.parent = User.objects.create_user(
            username="parent2", password="pw12345!", role=User.Roles.PARENT
        )
        self.operator = User.objects.create_user(
            username="operator1", password="pw12345!", role=User.Roles.OPERATOR
        )

    def test_role_claim_shape_for_parent_and_operator(self):
        for username, expected_role in (("parent2", "PARENT"), ("operator1", "OPERATOR")):
            response = self.client.post(
                "/api/token/",
                {"username": username, "password": "pw12345!"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            payload = _decode_jwt_payload(response.json()["access"])
            self.assertEqual(payload["role"], expected_role)
            self.assertIn("is_superuser", payload)

    def test_role_claim_survives_refresh(self):
        token_response = self.client.post(
            "/api/token/",
            {"username": "operator1", "password": "pw12345!"},
            content_type="application/json",
        )
        refresh = token_response.json()["refresh"]

        refresh_response = self.client.post(
            "/api/token/refresh/",
            {"refresh": refresh},
            content_type="application/json",
        )
        self.assertEqual(refresh_response.status_code, 200)

        new_access_payload = _decode_jwt_payload(refresh_response.json()["access"])
        # Confirms empirically (rather than assumed from SimpleJWT internals)
        # that get_token()'s custom claims - set on the refresh token - carry
        # over into an access token minted later from a plain refresh call,
        # with no TokenRefreshSerializer override needed.
        self.assertEqual(new_access_payload["role"], "OPERATOR")

    def test_login_is_throttled(self):
        # DRF's SimpleRateThrottle.THROTTLE_RATES is a class attribute read
        # once at import time (not re-read per request), so overriding
        # settings.REST_FRAMEWORK inside a test cannot retroactively change
        # it - this exercises the real configured rate (settings.py:
        # 'login': '10/min') rather than a synthetic one.
        rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]
        limit = int(rate.split("/")[0])

        responses = [
            self.client.post(
                "/api/token/",
                {"username": "parent2", "password": "wrong-password"},
                content_type="application/json",
            )
            for _ in range(limit + 1)
        ]
        self.assertTrue(all(r.status_code == 401 for r in responses[:limit]))
        self.assertEqual(responses[limit].status_code, 429)


class CrossParentIsolationTest(TestCase):
    """The core privacy guarantee of the whole app - one parent must never
    see another parent's child - had zero regression coverage before this.
    """

    def setUp(self):
        self.parent_a = User.objects.create_user(username="iso-parent-a", password="pw12345!", role=User.Roles.PARENT)
        self.parent_b = User.objects.create_user(username="iso-parent-b", password="pw12345!", role=User.Roles.PARENT)
        self.operator = User.objects.create_user(username="iso-operator", password="pw12345!", role=User.Roles.OPERATOR)

        van = Van.objects.create(name="ISO-VAN", tracker_imei="ISO-IMEI")
        school = GeoFence.objects.create(name="ISO School", location_type=GeoFence.LocationTypes.SCHOOL, latitude=25.5, longitude=-80.5, radius=50, traccar_id=401)
        gym = GeoFence.objects.create(name="ISO Gym", location_type=GeoFence.LocationTypes.GINAS_GYM, latitude=25.6, longitude=-80.6, radius=50, traccar_id=402)
        route = Route.objects.create(van=van, origin=school, destination=gym)

        self.child_a = Child.objects.create(name="Child A", parent=self.parent_a, route=route)
        self.child_b = Child.objects.create(name="Child B", parent=self.parent_b, route=route)

        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.parent_a)
        self.client_operator = APIClient()
        self.client_operator.force_authenticate(user=self.operator)

    def test_parent_children_list_excludes_other_parents(self):
        response = self.client_a.get("/api/children/")
        ids = [c["id"] for c in response.json()]
        self.assertIn(self.child_a.id, ids)
        self.assertNotIn(self.child_b.id, ids)

    def test_parent_schedules_list_excludes_other_parents(self):
        from .models import ChildSchedule

        ChildSchedule.objects.create(child=self.child_a, weekday=0, pickup_hour="15:00")
        ChildSchedule.objects.create(child=self.child_b, weekday=0, pickup_hour="15:00")

        response = self.client_a.get("/api/schedules/")
        child_ids = [s["child"] for s in response.json()]
        self.assertIn(self.child_a.id, child_ids)
        self.assertNotIn(self.child_b.id, child_ids)

    def test_operator_sees_all_children(self):
        response = self.client_operator.get("/api/children/")
        ids = {c["id"] for c in response.json()}
        self.assertEqual(ids, {self.child_a.id, self.child_b.id})

    def test_parent_cannot_write_even_their_own_child(self):
        # IsOperatorOrReadOnly blocks writes for non-operators outright - not
        # just other parents' data, the owning parent too. Parents don't edit
        # their own child records; the gym/operator does.
        response = self.client_a.patch(
            f"/api/children/{self.child_a.id}/",
            {"name": "Renamed"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
