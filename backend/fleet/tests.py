from unittest.mock import patch

from accounts.models import Child, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from . import traccar_client
from .models import GeoFence, Route, Van


class RouteCleanTest(TestCase):
    """Route.clean() is a real data-integrity rule (a route must go from a
    school to the gym) enforced on every save() via full_clean() - it had
    zero test coverage despite that.
    """

    def setUp(self):
        self.van = Van.objects.create(name="VAN-1", tracker_imei="IMEI0001")
        self.school = GeoFence.objects.create(
            name="School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.7, longitude=-80.4, radius=50, traccar_id=201,
        )
        self.gym = GeoFence.objects.create(
            name="Gym", location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.8, longitude=-80.5, radius=50, traccar_id=202,
        )
        self.other_school = GeoFence.objects.create(
            name="Other School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.9, longitude=-80.6, radius=50, traccar_id=203,
        )

    def test_valid_route_saves(self):
        route = Route(van=self.van, origin=self.school, destination=self.gym)
        route.save()
        self.assertIsNotNone(route.pk)

    def test_non_school_origin_rejected(self):
        with self.assertRaises(ValidationError):
            Route.objects.create(van=self.van, origin=self.gym, destination=self.gym)

    def test_non_gym_destination_rejected(self):
        with self.assertRaises(ValidationError):
            Route.objects.create(van=self.van, origin=self.school, destination=self.other_school)


class FleetPermissionScopingTest(TestCase):
    """Mirrors the same read/write scoping pattern accounts.tests verifies
    for children/schedules, for the fleet app's three ModelViewSets.
    """

    def setUp(self):
        self.parent_a = User.objects.create_user(username="fleet-parent-a", password="pw12345!", role=User.Roles.PARENT)
        self.parent_b = User.objects.create_user(username="fleet-parent-b", password="pw12345!", role=User.Roles.PARENT)
        self.operator = User.objects.create_user(username="fleet-operator", password="pw12345!", role=User.Roles.OPERATOR)

        self.van_a = Van.objects.create(name="VAN-A", tracker_imei="IMEI-A")
        self.van_b = Van.objects.create(name="VAN-B", tracker_imei="IMEI-B")
        school_a = GeoFence.objects.create(name="School A", location_type=GeoFence.LocationTypes.SCHOOL, latitude=25.1, longitude=-80.1, radius=50, traccar_id=301)
        gym_a = GeoFence.objects.create(name="Gym A", location_type=GeoFence.LocationTypes.GINAS_GYM, latitude=25.2, longitude=-80.2, radius=50, traccar_id=302)
        school_b = GeoFence.objects.create(name="School B", location_type=GeoFence.LocationTypes.SCHOOL, latitude=25.3, longitude=-80.3, radius=50, traccar_id=303)
        gym_b = GeoFence.objects.create(name="Gym B", location_type=GeoFence.LocationTypes.GINAS_GYM, latitude=25.4, longitude=-80.4, radius=50, traccar_id=304)

        self.route_a = Route.objects.create(van=self.van_a, origin=school_a, destination=gym_a)
        self.route_b = Route.objects.create(van=self.van_b, origin=school_b, destination=gym_b)

        Child.objects.create(name="Child A", parent=self.parent_a, route=self.route_a)
        Child.objects.create(name="Child B", parent=self.parent_b, route=self.route_b)

        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.parent_a)
        self.client_operator = APIClient()
        self.client_operator.force_authenticate(user=self.operator)

    def test_parent_sees_only_own_route(self):
        response = self.client_a.get("/api/routes/")
        ids = [r["id"] for r in response.json()]
        self.assertIn(self.route_a.id, ids)
        self.assertNotIn(self.route_b.id, ids)

    def test_parent_sees_only_own_van(self):
        response = self.client_a.get("/api/vans/")
        ids = [v["id"] for v in response.json()]
        self.assertIn(self.van_a.id, ids)
        self.assertNotIn(self.van_b.id, ids)

    def test_operator_sees_all_routes_and_vans(self):
        routes = self.client_operator.get("/api/routes/").json()
        vans = self.client_operator.get("/api/vans/").json()
        self.assertEqual({r["id"] for r in routes}, {self.route_a.id, self.route_b.id})
        self.assertEqual({v["id"] for v in vans}, {self.van_a.id, self.van_b.id})

    def test_parent_write_forbidden_even_on_own_route(self):
        response = self.client_a.patch(
            f"/api/routes/{self.route_a.id}/",
            {"van": self.van_b.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_write_allowed(self):
        van_c = Van.objects.create(name="VAN-C", tracker_imei="IMEI-C")
        response = self.client_operator.patch(
            f"/api/routes/{self.route_a.id}/",
            {"van": van_c.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)


class GeoFenceTraccarProvisioningTest(TestCase):
    """GeoFenceViewSet.perform_create/update/destroy call out to Traccar's own
    REST API to keep our GeoFence rows and Traccar's zones in sync - see
    fleet/traccar_client.py. Mocked here the same way accounts.tests mocks
    Twilio (@patch at the call site), since there's no live Traccar in CI.
    """

    def setUp(self):
        self.operator = User.objects.create_user(username="geofence-operator", password="pw12345!", role=User.Roles.OPERATOR)
        self.client_operator = APIClient()
        self.client_operator.force_authenticate(user=self.operator)

    @patch("fleet.views.traccar_client.create_geofence")
    def test_create_success_saves_returned_traccar_id(self, create_geofence):
        create_geofence.return_value = 999
        response = self.client_operator.post(
            "/api/geofences/",
            {"name": "New School", "location_type": "SCHOOL", "latitude": "25.5", "longitude": "-80.5", "radius": 50},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["traccar_id"], 999)
        create_geofence.assert_called_once_with("New School", 25.5, -80.5, 50.0)
        self.assertEqual(GeoFence.objects.get(name="New School").traccar_id, 999)

    @patch("fleet.views.traccar_client.create_geofence")
    def test_create_failure_persists_no_row(self, create_geofence):
        create_geofence.side_effect = traccar_client.TraccarAPIError("boom")
        response = self.client_operator.post(
            "/api/geofences/",
            {"name": "Doomed", "location_type": "SCHOOL", "latitude": "25.5", "longitude": "-80.5", "radius": 50},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(GeoFence.objects.filter(name="Doomed").exists())

    @patch("fleet.views.traccar_client.update_geofence")
    def test_update_calls_traccar_with_resolved_fields(self, update_geofence):
        fence = GeoFence.objects.create(
            name="Old Name", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.1, longitude=-80.1, radius=40, traccar_id=555,
        )
        response = self.client_operator.patch(
            f"/api/geofences/{fence.id}/", {"name": "New Name"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        update_geofence.assert_called_once_with(555, "New Name", 25.1, -80.1, 40.0)

    @patch("fleet.views.traccar_client.update_geofence")
    def test_update_skips_traccar_when_only_is_active_changes(self, update_geofence):
        fence = GeoFence.objects.create(
            name="Fence", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.1, longitude=-80.1, radius=40, traccar_id=556, is_active=True,
        )
        response = self.client_operator.patch(
            f"/api/geofences/{fence.id}/", {"is_active": False}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        update_geofence.assert_not_called()

    @patch("fleet.views.traccar_client.delete_geofence")
    def test_delete_removes_row_even_if_traccar_call_fails(self, delete_geofence):
        delete_geofence.side_effect = traccar_client.TraccarAPIError("unreachable")
        fence = GeoFence.objects.create(
            name="Fence", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.1, longitude=-80.1, radius=40, traccar_id=557,
        )
        response = self.client_operator.delete(f"/api/geofences/{fence.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(GeoFence.objects.filter(id=fence.id).exists())

    @patch("fleet.views.traccar_client.delete_geofence")
    def test_delete_protected_geofence_returns_400_not_500(self, delete_geofence):
        van = Van.objects.create(name="VAN-P", tracker_imei="IMEI-P")
        school = GeoFence.objects.create(
            name="Protected School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.1, longitude=-80.1, radius=40, traccar_id=558,
        )
        gym = GeoFence.objects.create(
            name="Gym", location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.2, longitude=-80.2, radius=40, traccar_id=559,
        )
        Route.objects.create(van=van, origin=school, destination=gym)

        response = self.client_operator.delete(f"/api/geofences/{school.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(GeoFence.objects.filter(id=school.id).exists())
        delete_geofence.assert_not_called()


class VanProtectedDeleteTest(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="van-operator", password="pw12345!", role=User.Roles.OPERATOR)
        self.client_operator = APIClient()
        self.client_operator.force_authenticate(user=self.operator)

    def test_delete_van_used_by_route_returns_400_not_500(self):
        van = Van.objects.create(name="VAN-Q", tracker_imei="IMEI-Q")
        school = GeoFence.objects.create(
            name="School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.1, longitude=-80.1, radius=40, traccar_id=601,
        )
        gym = GeoFence.objects.create(
            name="Gym", location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.2, longitude=-80.2, radius=40, traccar_id=602,
        )
        Route.objects.create(van=van, origin=school, destination=gym)

        response = self.client_operator.delete(f"/api/vans/{van.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Van.objects.filter(id=van.id).exists())


class MultiChildSameRouteTest(TestCase):
    """Regression: siblings usually ride the same route, which joins back to
    the same Route/Van row once per matching child in RouteViewSet's and
    VanViewSet's parent-scoped querysets. Without .distinct(), that
    duplicate row turned a retrieve into Route.MultipleObjectsReturned - a
    500, not a permissions issue, so it was never caught by the
    single-child scoping tests above."""

    def setUp(self):
        self.parent = User.objects.create_user(username="two-kids-parent", password="pw12345!", role=User.Roles.PARENT)
        self.van = Van.objects.create(name="TWO-KIDS-VAN", tracker_imei="TWO-KIDS-IMEI")
        school = GeoFence.objects.create(name="Two Kids School", location_type=GeoFence.LocationTypes.SCHOOL, latitude=25.5, longitude=-80.5, radius=50, traccar_id=401)
        gym = GeoFence.objects.create(name="Two Kids Gym", location_type=GeoFence.LocationTypes.GINAS_GYM, latitude=25.6, longitude=-80.6, radius=50, traccar_id=402)
        self.route = Route.objects.create(van=self.van, origin=school, destination=gym)
        Child.objects.create(name="Sibling One", parent=self.parent, route=self.route)
        Child.objects.create(name="Sibling Two", parent=self.parent, route=self.route)

        self.client_parent = APIClient()
        self.client_parent.force_authenticate(user=self.parent)

    def test_retrieving_the_shared_route_does_not_500(self):
        response = self.client_parent.get(f"/api/routes/{self.route.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.route.id)

    def test_retrieving_the_shared_van_does_not_500(self):
        response = self.client_parent.get(f"/api/vans/{self.van.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.van.id)

    def test_list_endpoints_do_not_duplicate_the_shared_row(self):
        routes = self.client_parent.get("/api/routes/").json()
        vans = self.client_parent.get("/api/vans/").json()
        self.assertEqual([r["id"] for r in routes], [self.route.id])
        self.assertEqual([v["id"] for v in vans], [self.van.id])
