from urllib.parse import parse_qs

import json

from accounts.models import Child, User
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from fleet.models import Van

from .models import Position
from .services import is_ride_active

GROUP_NAME = "van_position"
OPERATORS_GROUP = f"{GROUP_NAME}_operators"

class VanPositionConsumer(AsyncWebsocketConsumer):
    @database_sync_to_async
    def get_child_for_parent(self, parent, child_id):
        try:
            # select_related so child.route.van_id below doesn't trigger a
            # lazy query from the async side of connect().
            return Child.objects.select_related("route").get(id=child_id, parent=parent)
        except (Child.DoesNotExist, ValueError):
            return None

    @database_sync_to_async
    def get_seed_positions(self, van_ids):
        """Last known fix per van, in the same shape as a live update.

        Without this the map is empty until the tracker's next ping - up to a
        minute of nothing after every page load - and the parent's staleness
        counter has no timestamp to count from until then.
        """
        out = []
        for van_id in van_ids:
            last = (
                Position.objects.filter(van_id=van_id)
                .order_by("-device_time")
                .first()
            )
            if last is None:
                continue
            out.append(
                json.dumps(
                    {
                        "van_id": last.van_id,
                        "lat": float(last.latitude),
                        "lon": float(last.longitude),
                        "course": float(last.course) if last.course is not None else None,
                        "device_time": last.device_time.isoformat(),
                    }
                )
            )
        return out

    @database_sync_to_async
    def get_all_van_ids(self):
        return list(Van.objects.values_list("id", flat=True))

    async def connect(self):
        user = self.scope["user"] #type: ignore

        if user.is_anonymous: # type: ignore
            await self.close(code=4001)
            return

        self.groups_joined = []

        self.route_id = None
        self.seed_van_ids = []

        if user.role == User.Roles.OPERATOR or user.is_superuser: #type: ignore
            self.groups_joined.append(OPERATORS_GROUP)
            self.seed_van_ids = await self.get_all_van_ids()
        else:
            query_dict = parse_qs(self.scope["query_string"].decode("utf-8")) # type: ignore
            child_id_list = query_dict.get("child_id")

            if not child_id_list:
                # No child specified - nothing to grant access to.
                await self.close(code=4002)
                return

            child = await self.get_child_for_parent(user, child_id_list[0])

            if child is None:
                # Doesn't exist or isn't this parent's child - same code either
                # way, so we don't leak which one it was.
                await self.close(code=4002)
                return

            if not is_ride_active(child):
                await self.close(code=4003)
                return

            self.child_id = child.id
            self.route_id = child.route_id
            self.seed_van_ids = [child.route.van_id]
            self.groups_joined.append(f"{GROUP_NAME}_{child.route.van_id}")

        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()

        # Seeded after accept() so the client is already listening. These are
        # indistinguishable from live updates on the wire, deliberately: the
        # client needs no separate code path for "first position".
        for payload in await self.get_seed_positions(self.seed_van_ids):
            await self.send(text_data=payload)

    async def receive(self, text_data):
        await self.send(text_data=text_data)

    async def disconnect(self, close_code):
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def van_position_update(self, event):
        await self.send(text_data=event["data"])

    async def ride_ended(self, event):
        # Everyone in this van's group gets the event, but it should only
        # close the socket watching the specific route that just ended -
        # not other children sharing the same van.
        if self.route_id == event["route_id"]:
            await self.close()
