
from channels.generic.websocket import AsyncWebsocketConsumer

GROUP_NAME = "van_position"

class VanPositionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(GROUP_NAME, self.channel_name)
        await self.accept()

    async def receive(self, text_data):
        await self.send(text_data=text_data)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_NAME, self.channel_name)

    async def van_position_update(self,event):
        await self.send(text_data=event["data"])
