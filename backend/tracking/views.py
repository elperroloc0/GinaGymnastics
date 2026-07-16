import json

from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from fleet.models import GeoFence, Van
from tracking.models import ArrivalEvent

# Create your views here.

TYPE_MAP = {
        "geofenceExit": ArrivalEvent.ArrivalType.EXIT,
        "geofenceEnter": ArrivalEvent.ArrivalType.ENTER,
    }

@csrf_exempt
def traccar_webhook(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    # print(json.dumps(data, indent=3))

    event_type = data.get("event", {}).get("type")
    if event_type not in TYPE_MAP:
        return JsonResponse({"status": "ignored"})

    arrival_type = TYPE_MAP[event_type]
    print(arrival_type)

    imei = data.get("device", {}).get("uniqueId")
    try:
        van = Van.objects.get(tracker_imei=imei)
    except Van.DoesNotExist:
        return JsonResponse({"status": "unknown device"})

    traccar_fence_id = data.get("event", {}).get("geofenceId")
    try:
        traccar_fence = GeoFence.objects.get(traccar_id=traccar_fence_id)
        print(traccar_fence)
    except GeoFence.DoesNotExist:
        return JsonResponse({"status": "unknown geo fence"})



    time = data.get("event", {}).get("eventTime")
    if time is not None:

        try:
            event_time = parse_datetime(time)
            print(event_time)
        except TypeError:
            return JsonResponse({"status": "Not valid datetime"})

    ArrivalEvent.objects.create(van=van, geo_fence=traccar_fence, arrival_type=arrival_type, time=time)

    # print(van, event_type, geo_fence, time)

    return JsonResponse({"status": "ok"})




'''curl -s -X POST http://127.0.0.1:8000/webhooks/traccar/ \
  -H "Content-Type: application/json" \
  -d '{"event": {"id": 2, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 3}, "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI12345"}, "geofence": {"id": 3, "name": "Ginas Gymnastics"}}'
'''


'''curl "http://localhost:5055/?id=IMEI12345&lat=25.72&lon=-80.43"
'''
