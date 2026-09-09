import json
import os
import uuid
from datetime import datetime, timedelta

from accounts.models import Child, User
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from fleet.models import GeoFence, Route, Van
from notifications.services import notify_parent
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tracking.models import ArrivalEvent

from .consumers import GROUP_NAME, OPERATORS_GROUP
from .serializers import ArrivalEventSerializer

TYPE_MAP = {
        "geofenceExit": ArrivalEvent.ArrivalType.EXIT,
        "geofenceEnter": ArrivalEvent.ArrivalType.ENTER,
    }


def _check_secret(request):
    web_secret = request.headers.get("X-Webhook-Secret")
    traccar_secret = os.environ.get("TRACCAR_WEBHOOK_SECRET", "")

    if web_secret != traccar_secret:
        return False

    return True

def _get_request_json(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return None
    # print(json.dumps(data, indent=3))
    return data


def _get_van(imei):
    try:
        return Van.objects.get(tracker_imei=imei)
    except Van.DoesNotExist:
        return None


@csrf_exempt
def arrival_webhook(request):
    if not _check_secret(request):
        return JsonResponse({"status": "invalid"}, status=403)

    data = _get_request_json(request)

    if not data:
        return JsonResponse({"error": "invalid json"}, status=400)

    event_type = data.get("event", {}).get("type")

    if event_type not in TYPE_MAP:
        return JsonResponse({"status": "ignored"})

    arrival_type = TYPE_MAP[event_type]

    imei = data.get("device", {}).get("uniqueId")
    van = _get_van(imei)

    if van is None:
        return JsonResponse({"status": "unknown device"})

    traccar_fence_id = data.get("event", {}).get("geofenceId")

    try:
        traccar_fence = GeoFence.objects.get(traccar_id=traccar_fence_id)
    except GeoFence.DoesNotExist:
        return JsonResponse({"status": "unknown geo fence"})

    time = data.get("event", {}).get("eventTime")

    if time is not None:
        try:
            event_time = parse_datetime(time)
        except TypeError:
            return JsonResponse({"status": "Not valid datetime"})

    ArrivalEvent.objects.create(van=van, geo_fence=traccar_fence, arrival_type=arrival_type, time=event_time)

    # Only arrivals (ENTER) drive ride state - a van leaving (EXIT) doesn't
    # need to flip active_ride either way, that's handled by the two branches below.
    if arrival_type == ArrivalEvent.ArrivalType.ENTER:

        # --- Ride may be starting: van reached a school (origin) ---
        # --- SCHOOL
        now = timezone.now()
        # Must use local time for weekday/date - pickup_hour is entered by
        # operators in local time, and now.weekday() (UTC) can disagree with the
        # local day near midnight.
        local_now = timezone.localtime(now)
        today_weekday = local_now.weekday()
        # Tolerance around the scheduled pickup time - GPS/webhook timing isn't
        # exact, and this also stops a parent from getting map access hours
        # before/after the actual pickup window.
        BUFFER = timedelta(minutes=30)

        school_route = Route.objects.filter(origin=traccar_fence)

        candidates = Child.objects.filter(route__in=school_route, schedule__weekday=today_weekday)

        for child in candidates:
            # unique_together=('child', 'weekday') on ChildSchedule guarantees
            # at most one row here, so .first() is safe.
            schedule = child.schedule.filter(weekday=today_weekday).first()
            scheduled_dt = timezone.make_aware(datetime.combine(local_now.date(), schedule.pickup_hour))
            # Two-sided check: the event can arrive slightly before or after
            # the scheduled pickup_hour.
            if abs(now - scheduled_dt) <= BUFFER:
                child.active_ride = True
                notify_parent(child, 'Van has arrived to the school. <link to live map>')
                child.active_ride_start = now
                child.save()

        # --- Ride ended: van reached the gym (destination) ---
        # Route.clean() guarantees destination is always a GYM-type geofence and
        # origin is always SCHOOL, so a single traccar_fence can only ever match
        # one of these two branches, never both.
        # --- GYM

        gym_route = Route.objects.filter(destination=traccar_fence)
        candidates = Child.objects.filter(route__in=gym_route)

        channel_layer = get_channel_layer()

        for child in candidates:
            child.active_ride = False
            notify_parent(child, 'Van has arrived to Ginas Gymnastics')
            child.save()

            # Close any live-map socket already open for this child's ride -
            # active_ride=False alone doesn't affect a connection that's
            # already been accepted.
            if channel_layer is not None:
                async_to_sync(channel_layer.group_send)(
                    f"{GROUP_NAME}_{child.route.van_id}",
                    {
                        "type": "ride_ended",
                        "route_id": child.route_id,
                    },
                )


    return JsonResponse({"status": "ok"})

@csrf_exempt
def traccar_position(request):
    if not _check_secret(request):
        return JsonResponse({"status": "invalid"}, status=403)

    data = _get_request_json(request)
    if not data:
        return JsonResponse({"error": "invalid json"}, status=400)

    lat = data.get("position", {}).get("latitude")
    lon = data.get("position", {}).get("longitude")

    imei = data.get("device", {}).get("uniqueId")
    van = _get_van(imei)
    if van is None:
        return JsonResponse({"status": "unknown device"})

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return JsonResponse({"status": "channel layer unavailable"}, status=500)

    async_to_sync(channel_layer.group_send)(
        f"{GROUP_NAME}_{van.id}",
        {
            "type": "van_position_update",
            "data": json.dumps({"lat": lat, "lon": lon}),
        },
    )
    async_to_sync(channel_layer.group_send)(
            f"{OPERATORS_GROUP}",
            {
                "type": "van_position_update",
                "data": json.dumps({"lat": lat, "lon": lon}),
            },
        )
    return JsonResponse({"status": "ok"})


class ArrivalEventList(generics.ListAPIView):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser: #type: ignore
            return ArrivalEvent.objects.all()

        return ArrivalEvent.objects.filter(geo_fence__routes_from__children__parent=user)

    serializer_class = ArrivalEventSerializer


class WebSocketTicketView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # generate ticket
        ticket = str(uuid.uuid4())

        # store in redis
        cache.set(f"ws_ticket:{ticket}", request.user.id, timeout=30)

        return Response({"ticket": ticket})






