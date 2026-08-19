from typing import Any
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache

User = get_user_model()

@database_sync_to_async
def get_user_from_ticket(ticket_string):
    cache_key = f"ws_ticket:{ticket_string}"
    user_id = cache.get(cache_key)

    if user_id:
        try:
            user = User.objects.get(id=user_id)
            cache.delete(cache_key)
            return user
        except User.DoesNotExist:
            pass

    return AnonymousUser()


class TicketAuthMiddleware():
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_dict = parse_qs(scope["query_string"].decode("utf-8"))
        ticket_list = query_dict.get("ticket")

        if ticket_list:
            # Extract ticket string and check against Redis
            scope["user"] = await get_user_from_ticket(ticket_list[0])
        else:
            scope["user"] = AnonymousUser()

        return await self.inner(scope, receive, send)


