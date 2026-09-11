import json
import os
from datetime import timedelta
from unittest.mock import patch

import pytest
from accounts.models import Child, ChildSchedule, User
from asgiref.sync import sync_to_async
from channels.testing import HttpCommunicator, WebsocketCommunicator
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from fleet.models import GeoFence, Route, Van
from rest_framework.test import APIClient

from backend.asgi import application

from .consumers import VanPositionConsumer
from .models import ArrivalEvent

# In-memory cache and channel layer: the suite must run without a live
# Redis, and test tickets must never land in the real instance.
in_memory_backends = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)


# Create your tests here.
class WebhookTest(TestCase):
    def setUp(self):
        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")
        self.school = GeoFence.objects.create(
            name="Test School",
            latitude=25.72,
            longitude=-80.43,
            radius=40,
            traccar_id=3,
        )

    def test_no_secret_rejected(self):
        response = self.client.post(
            "/webhooks/arrival/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_event_created(self):
        secret = os.environ["TRACCAR_WEBHOOK_SECRET"]
        response = self.client.post(
            "/webhooks/arrival/",
            data={
                "event": {
                    "id": 1,
                    "deviceId": 1,
                    "type": "geofenceEnter",
                    "eventTime": "2026-07-15T18:30:17.386+00:00",
                    "positionId": 9,
                    "geofenceId": 3,
                },
                "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI12345"},
                "geofence": {"id": 3, "name": "Test School"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": secret},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ArrivalEvent.objects.count(), 1)

    def test_event_with_no_secret(self):
        response = self.client.post(
            "/webhooks/arrival/",
            data={
                "event": {
                    "id": 1,
                    "deviceId": 1,
                    "type": "geofenceEnter",
                    "eventTime": "2026-07-15T18:30:17.386+00:00",
                    "positionId": 9,
                    "geofenceId": 3,
                },
                "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"},
                "geofence": {"id": 3, "name": "Test School"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": ""},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ArrivalEvent.objects.count(), 0)

    def test_wrong_secret_rejected(self):
        response = self.client.post(
            "/webhooks/arrival/",
            data={
                "event": {
                    "id": 1,
                    "deviceId": 1,
                    "type": "geofenceEnter",
                    "eventTime": "2026-07-15T18:30:17.386+00:00",
                    "positionId": 9,
                    "geofenceId": 3,
                },
                "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"},
                "geofence": {"id": 3, "name": "Test School"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": "wrong-key"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ArrivalEvent.objects.count(), 0)

    def test_foreign_event_ignored(self):
        secret = os.environ["TRACCAR_WEBHOOK_SECRET"]
        response = self.client.post(
            "/webhooks/arrival/",
            data={
                "event": {
                    "id": 1,
                    "deviceId": 1,
                    "type": "deviceStopped",
                    "eventTime": "2026-07-15T18:30:17.386+00:00",
                    "positionId": 9,
                    "geofenceId": 3,
                },
                "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"},
                "geofence": {"id": 3, "name": "Test School"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": secret},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ArrivalEvent.objects.count(), 0)


@in_memory_backends
class PositionViewTest(TestCase):
    def setUp(self):
        self.secret = os.environ["TRACCAR_WEBHOOK_SECRET"]
        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")

    def test_wrong_secret_rejected(self):
        response = self.client.post(
            "/webhooks/position/",
            data={
                "event": {
                    "id": 1,
                    "deviceId": 1,
                    "type": "deviceStopped",
                    "eventTime": "2026-07-15T18:30:17.386+00:00",
                    "positionId": 9,
                    "geofenceId": 3,
                },
                "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"},
                "geofence": {"id": 3, "name": "Test School"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": "wrong secret"},
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_request_passes(self):
        response = self.client.post(
            "/webhooks/position/",
            data={
                "position": {"latitude": 25.72, "longitude": -80.43},
                "device": {"uniqueId": "IMEI12345"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": self.secret},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_broken_json(self):
        response = self.client.post(
            "/webhooks/position/",
            data={"not valid json"},
            content_type="application/json",
            headers={"X-Webhook-Secret": self.secret},
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_van_rejected(self):
        response = self.client.post(
            "/webhooks/position/",
            data={
                "position": {"latitude": 25.72, "longitude": -80.43},
                "device": {"uniqueId": "UNKNOWN-DEVICE"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": self.secret},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unknown device")


class EventListPermissionTest(TestCase):
    def setUp(self):
        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")
        self.school_1 = GeoFence.objects.create(
            name="Test School 1",
            latitude=25.72,
            longitude=-80.43,
            radius=40,
            traccar_id=1,
        )
        self.school_2 = GeoFence.objects.create(
            name="Test School 2",
            latitude=26.72,
            longitude=-81.43,
            radius=40,
            traccar_id=2,
        )
        self.gym = GeoFence.objects.create(
            name="Test Gym",
            location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.80,
            longitude=-80.50,
            radius=40,
            traccar_id=99,
        )
        self.route = Route.objects.create(
            van=self.van, origin=self.school_1, destination=self.gym
        )

        self.admin = User.objects.create_superuser(
            username="admin1", email="", password="unsecure12345"
        )
        self.parent = User.objects.create(
            username="parent", password="unsecure12345", role=User.Roles.PARENT
        )
        self.child = Child.objects.create(
            name="child 1",
            parent=self.parent,
            route=self.route,
        )

        ArrivalEvent.objects.create(
            van=self.van,
            geo_fence=self.school_1,
            arrival_type=ArrivalEvent.ArrivalType.ENTER,
            time="2012-09-04 06:00:00.000000+0800",
        )

        ArrivalEvent.objects.create(
            van=self.van,
            geo_fence=self.school_2,
            arrival_type=ArrivalEvent.ArrivalType.ENTER,
            time="2012-09-04 07:00:00.000000+0800",
        )

    def test_anonymous_rejected(self):
        response = self.client.get("/api/events/")
        self.assertEqual(response.status_code, 401)

    def test_parent_sees_only_school(self):
        client = APIClient()
        client.force_authenticate(user=self.parent)
        response = client.get("/api/events/")
        data = response.json()  # type: ignore
        self.assertEqual(len(data), 1)

    def test_admin_sees_all_events(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/events/")
        data = response.json()  # type: ignore
        self.assertEqual(len(data), 2)


class TaskTest(TestCase):
    def setUp(self):
        self.secret = os.environ["TRACCAR_WEBHOOK_SECRET"]

        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")
        self.school = GeoFence.objects.create(
            name="Test School",
            latitude=25.72,
            longitude=-80.43,
            radius=40,
            traccar_id=1,
        )
        self.gym = GeoFence.objects.create(
            name="Test Gym",
            location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.80,
            longitude=-80.50,
            radius=40,
            traccar_id=98,
        )
        self.route = Route.objects.create(
            van=self.van, origin=self.school, destination=self.gym
        )

        self.parent = User.objects.create(
            username="parent",
            password="unsecure12345",
            role=User.Roles.PARENT,
            phone_number="+17869167736",
        )
        self.child = Child.objects.create(
            name="child 1",
            parent=self.parent,
            route=self.route,
        )

        # arrival_webhook only notifies children scheduled for today, within a
        # buffer of pickup_hour - so the schedule has to match "now" for this
        # test to trigger a notification at all.
        now = timezone.localtime(timezone.now())
        ChildSchedule.objects.create(
            child=self.child, weekday=now.weekday(), pickup_hour=now.time()
        )

        ArrivalEvent.objects.create(
            van=self.van,
            geo_fence=self.school,
            arrival_type=ArrivalEvent.ArrivalType.ENTER,
            time="2012-09-04 06:00:00.000000+0800",
        )

    @patch("notifications.services.debug_sms")
    def test_task_is_created(self, mock_task):
        response = self.client.post(
            "/webhooks/arrival/",
            data={
                "event": {
                    "id": 1,
                    "deviceId": 1,
                    "type": "geofenceEnter",
                    "eventTime": "2026-07-15T18:30:17.386+00:00",
                    "positionId": 9,
                    "geofenceId": 1,
                },
                "device": {"id": 1, "name": "TEST-VAN", "uniqueId": "IMEI12345"},
                "geofence": {"id": 1, "name": "Test School"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": self.secret},
        )
        mock_task.delay_on_commit.assert_called_once()


@in_memory_backends
class WebSocketAuthTest(TransactionTestCase):
    # Not TestCase: these tests drive an ASGI consumer through
    # database_sync_to_async, which runs its ORM calls on a different thread
    # than the test method itself. TestCase's per-test transaction lives only
    # on the main thread's connection, so a query from that other thread can
    # find it already torn down mid-test ("the connection is closed") against
    # a real database (Postgres in particular - sqlite's looser locking can
    # mask it). TransactionTestCase runs each test against real committed
    # state instead of a rolled-back transaction, which every thread sees
    # consistently, at the cost of resetting tables via truncation instead of
    # a (faster) rollback.
    ORIGIN_HEADERS = [(b"origin", b"http://localhost:8000")]

    async def asyncSetUp(self):
        # Operator, not parent: these tests are about ticket validity, not
        # about the child/active-ride gating below - that has its own tests.
        self.user = await User.objects.acreate(
            username="ws-test-user", password="unsecure12345", role=User.Roles.OPERATOR
        )
        self.van = await Van.objects.acreate(name="TEST-VAN", tracker_imei="IMEI12345")

    async def test_valid_ticket_is_accepted(self):
        await self.asyncSetUp()
        cache.set("ws_ticket:valid-ticket", self.user.id, timeout=30)

        communicator = WebsocketCommunicator(
            application, "/ws/van/?ticket=valid-ticket", headers=self.ORIGIN_HEADERS
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_ticket_is_single_use(self):
        await self.asyncSetUp()
        cache.set("ws_ticket:reuse-ticket", self.user.id, timeout=30)

        first = WebsocketCommunicator(
            application, "/ws/van/?ticket=reuse-ticket", headers=self.ORIGIN_HEADERS
        )
        connected, _ = await first.connect()
        self.assertTrue(connected)
        await first.disconnect()

        second = WebsocketCommunicator(
            application, "/ws/van/?ticket=reuse-ticket", headers=self.ORIGIN_HEADERS
        )
        connected_again, close_code = await second.connect()
        self.assertFalse(connected_again)
        self.assertEqual(close_code, 4001)

    async def test_unknown_ticket_is_rejected(self):
        communicator = WebsocketCommunicator(
            application, "/ws/van/?ticket=does-not-exist", headers=self.ORIGIN_HEADERS
        )
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4001)

    async def test_missing_ticket_is_rejected(self):
        communicator = WebsocketCommunicator(
            application, "/ws/van/", headers=self.ORIGIN_HEADERS
        )
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4001)

    async def test_receive_layer_group(self):
        self.secret = os.environ["TRACCAR_WEBHOOK_SECRET"]

        self.user = await User.objects.acreate(
            username="user123",
            password="unsecure123",
            role="OPERATOR"
        )
        self.van = await Van.objects.acreate(
            name="TEST-VAN",
            tracker_imei="IMEI12345"
        )
        cache.set("ws_ticket:valid-ticket", self.user.id, timeout=30)

        communicator = WebsocketCommunicator(application, "/ws/van/?ticket=valid-ticket", headers=self.ORIGIN_HEADERS)

        connected, _ = await communicator.connect()

        self.assertTrue(connected)

        await sync_to_async(self.client.post)(
            "/webhooks/position/",
            data={
                "position": {"latitude": 25.72, "longitude": -80.43},
                "device": {"uniqueId": "IMEI12345"},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": self.secret},)

        result = await communicator.receive_from()
        result = json.loads(result)

        # van_id lets an operator watching every van tell them apart;
        # device_time is what the parent's staleness counter measures from.
        self.assertEqual(result["lat"], 25.72)
        self.assertEqual(result["lon"], -80.43)
        self.assertEqual(result["van_id"], self.van.id)
        self.assertIn("device_time", result)
        await communicator.disconnect()

    async def _make_child(self, parent, imei, traccar_id_offset, **child_kwargs):
        van = await Van.objects.acreate(name=f"VAN-{imei}", tracker_imei=imei)
        school = await GeoFence.objects.acreate(
            name=f"School-{traccar_id_offset}",
            location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.0, longitude=-80.0, radius=40,
            traccar_id=traccar_id_offset,
        )
        gym = await GeoFence.objects.acreate(
            name=f"Gym-{traccar_id_offset}",
            location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.1, longitude=-80.1, radius=40,
            traccar_id=traccar_id_offset + 1,
        )
        route = await Route.objects.acreate(van=van, origin=school, destination=gym)
        child = await Child.objects.acreate(name="Test Child", parent=parent, route=route, **child_kwargs)
        # Stashed for tests that need to simulate webhook events for this
        # child's route - not real model fields.
        child._test_van = van
        child._test_gym = gym
        return child

    async def test_parent_missing_child_id_rejected(self):
        parent = await User.objects.acreate(username="parent-no-child-id", password="unsecure12345")
        cache.set("ws_ticket:no-child-id", parent.id, timeout=30)

        communicator = WebsocketCommunicator(
            application, "/ws/van/?ticket=no-child-id", headers=self.ORIGIN_HEADERS
        )
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4002)

    async def test_parent_wrong_child_rejected(self):
        parent = await User.objects.acreate(username="parent-wrong-child", password="unsecure12345")
        other_parent = await User.objects.acreate(username="other-parent", password="unsecure12345")
        others_child = await self._make_child(other_parent, "IMEI-WRONG", 601)

        cache.set("ws_ticket:wrong-child", parent.id, timeout=30)

        communicator = WebsocketCommunicator(
            application,
            f"/ws/van/?ticket=wrong-child&child_id={others_child.id}",
            headers=self.ORIGIN_HEADERS,
        )
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4002)

    async def test_parent_child_without_active_ride_rejected(self):
        parent = await User.objects.acreate(username="parent-inactive", password="unsecure12345")
        child = await self._make_child(parent, "IMEI-INACTIVE", 603)  # active_ride defaults to False

        cache.set("ws_ticket:inactive-ride", parent.id, timeout=30)

        communicator = WebsocketCommunicator(
            application,
            f"/ws/van/?ticket=inactive-ride&child_id={child.id}",
            headers=self.ORIGIN_HEADERS,
        )
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4003)

    async def test_parent_child_with_active_ride_accepted(self):
        parent = await User.objects.acreate(username="parent-active", password="unsecure12345")
        child = await self._make_child(
            parent, "IMEI-ACTIVE", 605, active_ride=True, active_ride_start=timezone.now()
        )

        cache.set("ws_ticket:active-ride", parent.id, timeout=30)

        communicator = WebsocketCommunicator(
            application,
            f"/ws/van/?ticket=active-ride&child_id={child.id}",
            headers=self.ORIGIN_HEADERS,
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_parent_stale_active_ride_rejected(self):
        parent = await User.objects.acreate(username="parent-stale", password="unsecure12345")
        child = await self._make_child(
            parent,
            "IMEI-STALE",
            607,
            active_ride=True,
            active_ride_start=timezone.now() - timedelta(hours=7),
        )

        cache.set("ws_ticket:stale-ride", parent.id, timeout=30)

        communicator = WebsocketCommunicator(
            application,
            f"/ws/van/?ticket=stale-ride&child_id={child.id}",
            headers=self.ORIGIN_HEADERS,
        )
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4003)

    async def test_ride_ended_closes_open_socket(self):
        parent = await User.objects.acreate(username="parent-ride-ends", password="unsecure12345")
        child = await self._make_child(
            parent, "IMEI-ENDING", 609, active_ride=True, active_ride_start=timezone.now()
        )

        cache.set("ws_ticket:ride-ending", parent.id, timeout=30)
        communicator = WebsocketCommunicator(
            application,
            f"/ws/van/?ticket=ride-ending&child_id={child.id}",
            headers=self.ORIGIN_HEADERS,
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Simulate Traccar reporting the van has arrived at the gym
        # (destination) for this child's route.
        await sync_to_async(self.client.post)(
            "/webhooks/arrival/",
            data={
                "event": {
                    "type": "geofenceEnter",
                    "eventTime": "2026-01-01T12:00:00.000+00:00",
                    "geofenceId": child._test_gym.traccar_id,
                },
                "device": {"uniqueId": child._test_van.tracker_imei},
            },
            content_type="application/json",
            headers={"X-Webhook-Secret": os.environ["TRACCAR_WEBHOOK_SECRET"]},
        )

        output = await communicator.receive_output(timeout=1)
        self.assertEqual(output["type"], "websocket.close")
