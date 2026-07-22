import json
import os

from accounts.models import User
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from fleet.models import GeoFence, Van
from notifications.tasks import debug_sms
from rest_framework import generics
from tracking.models import ArrivalEvent

from .serializers import ArrivalEventSerializer

# Create your views here.

TYPE_MAP = {
        "geofenceExit": ArrivalEvent.ArrivalType.EXIT,
        "geofenceEnter": ArrivalEvent.ArrivalType.ENTER,
    }


@csrf_exempt
def traccar_webhook(request):
    web_secret = request.headers.get("X-Webhook-Secret")
    traccar_secret = os.environ.get("TRACCAR_WEBHOOK_SECRET", "")

    if web_secret != traccar_secret:
        return JsonResponse({"status": "invalid"}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    # print(json.dumps(data, indent=3))

    event_type = data.get("event", {}).get("type")
    if event_type not in TYPE_MAP:
        return JsonResponse({"status": "ignored"})

    arrival_type = TYPE_MAP[event_type]
    # print(arrival_type)

    imei = data.get("device", {}).get("uniqueId")
    try:
        van = Van.objects.get(tracker_imei=imei)
    except Van.DoesNotExist:
        return JsonResponse({"status": "unknown device"})

    traccar_fence_id = data.get("event", {}).get("geofenceId")
    try:
        traccar_fence = GeoFence.objects.get(traccar_id=traccar_fence_id)
        # print(traccar_fence)
    except GeoFence.DoesNotExist:
        return JsonResponse({"status": "unknown geo fence"})

    time = data.get("event", {}).get("eventTime")
    if time is not None:

        try:
            event_time = parse_datetime(time)
            # print(event_time)
        except TypeError:
            return JsonResponse({"status": "Not valid datetime"})

    ArrivalEvent.objects.create(van=van, geo_fence=traccar_fence, arrival_type=arrival_type, time=event_time)

    parents = User.objects.filter(children__school=traccar_fence).distinct()

    for parent in parents:
        if not parent.phone_number:
            pass

        else:
            debug_sms.delay_on_commit(str(parent.phone_number), 'child has arrived')


    # print(van, event_type, geo_fence, time)

    return JsonResponse({"status": "ok"})


class ArrivalEventList(generics.ListAPIView):

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:
            return ArrivalEvent.objects.all()

        return ArrivalEvent.objects.filter(geo_fence__children__parent=user)

    serializer_class = ArrivalEventSerializer











'''curl -s -X POST http://127.0.0.1:8000/webhooks/traccar/ \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: secret" \
  -d '{"event": {"id": 2, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 1}, "device": {"id": 1, "name": "Cla", "uniqueId": "862464068675730"}, "geofence": {"id": 1, "name": "Home"}}'
'''


'''curl "http://localhost:5055/?id=IMEI12345&lat=25.72&lon=-80.43"
'''
