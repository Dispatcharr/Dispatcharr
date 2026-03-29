import json
from channels.generic.websocket import AsyncWebsocketConsumer
import regex, logging

logger = logging.getLogger(__name__)

class MyWebSocketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = "updates"

        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return

        try:
            await self.accept()
            await self.channel_layer.group_add(self.room_name, self.channel_name)
            # Send a connection confirmation to the client with consistent format
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'data': {
                    'success': True,
                    'message': 'WebSocket connection established successfully'
                }
            }))
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in WebSocket connect: {str(e)}")
            # If an error occurs during connection, attempt to close
            try:
                await self.close(code=1011)  # Internal server error
            except:
                pass

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.room_name, self.channel_name)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in WebSocket disconnect: {str(e)}")

    async def receive(self, text_data):
        data = json.loads(text_data)

        if data["type"] == "m3u_profile_test":
            from apps.proxy.ts_proxy.url_utils import transform_url

            def replace_with_mark(match):
                # Wrap the match in <mark> tags
                return f"<mark>{match.group(0)}</mark>"

            # Apply the transformation using the replace_with_mark function
            try:
                search_preview = regex.sub(data["search"], replace_with_mark, data["url"])
            except Exception as e:
                search_preview = data["url"]
                logger.error(f"Failed to generate replace preview: {e}")

            result = transform_url(data["url"], data["search"], data["replace"])
            await self.send(text_data=json.dumps({
                "data": {
                   'type': 'm3u_profile_test',
                    'search_preview': search_preview,
                    'result': result,
                }
            }))

    async def update(self, event):
        await self.send(text_data=json.dumps(event))
