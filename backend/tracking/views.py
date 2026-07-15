import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

# Create your views here.

@csrf_exempt
def traccar_webhook(self):
    return JsonResponse({"status": "ok"})
