from accounts.models import Child, User
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

GROUP_NAME = "van_position"
OPERATORS_GROUP = f"{GROUP_NAME}_operators"

class VanPositionConsumer(AsyncWebsocketConsumer):
    @database_sync_to_async
    def get_parent_van_id(self, parent):
        child = Child.objects.filter(parent=parent).first()
        if not child:
            return None
        return child.route.van_id

    async def connect(self):
        user = self.scope["user"] #type: ignore

        if user.is_anonymous: # type: ignore
            await self.close(code=4001)
            return

        self.groups_joined = []

        if user.role == User.Roles.OPERATOR or user.is_superuser: #type: ignore
            self.groups_joined.append(OPERATORS_GROUP)
        else:
            van_id = await self.get_parent_van_id(user)
            if van_id is not None:
                self.groups_joined.append(f"{GROUP_NAME}_{van_id}")

        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()

    async def receive(self, text_data):
        await self.send(text_data=text_data)

    async def disconnect(self, close_code):
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def van_position_update(self,event):
        await self.send(text_data=event["data"])
