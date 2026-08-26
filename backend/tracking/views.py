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
from notifications.tasks import debug_sms
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

today = datetime.now()

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

    if arrival_type == ArrivalEvent.ArrivalType.ENTER:
        # сhildren have arrived to gym:
        # flag as inactive ride
        gym_route = Route.objects.filter(destination=traccar_fence)
        Child.objects.filter(route__in=gym_route).update(active_ride=False)

        # Van arrived to school:
        # flag as active ride
        # Notify parents when van arrived
        now = timezone.now()
        today_weekday = now.weekday()
        BUFFER = timedelta(minutes=30)

        school_route = Route.objects.filter(origin=traccar_fence)
        candidates = Child.objects.filter(route__in=school_route, schedule__weekday=today_weekday)

        local_now = timezone.localtime(now)

        for child in candidates:
            schedule = child.schedule.filter(weekday=today_weekday).first()
            scheduled_dt = timezone.make_aware(datetime.combine(local_now.date(), schedule.pickup_hour))
            if abs(now - scheduled_dt) <= BUFFER:
                child.active_ride = True
                child.active_ride_start = now
                child.save()

        parents = User.objects.filter(children__route__origin=traccar_fence).distinct()

        for parent in parents:
            if not parent.phone_number:
                continue

            debug_sms.delay_on_commit(str(parent.phone_number), 'Van has arrived to the school. <link to live map>') # type: ignore

        # TODO: Notify parents when van has arrived to gym

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






'''curl -s -X POST http://127.0.0.1:8000/webhooks/arrival/ \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: secret" \
  -d '{"event": {"id": 2, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 1}, "device": {"id": 1, "name": "Cla", "uniqueId": "862464068675730"}, "geofence": {"id": 1, "name": "Home"}}'
'''


'''curl "http://localhost:5055/?id=IMEI12345&lat=25.72&lon=-80.43"
'''
