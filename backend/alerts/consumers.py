"""Optional WebSocket push for the officer dashboard.

Best-effort only: the dashboard polls REST and is fully functional without a
channel layer. Only already-safety-verified alert summaries are broadcast, and
only to authenticated health officers.
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer

GROUP = "officer_alerts"


class OfficerAlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        if getattr(user, "role", None) not in {"HEALTH_OFFICER", "ADMIN"}:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()
        await self.send(json.dumps({"type": "connected", "group": GROUP}))

    async def disconnect(self, code):
        try:
            await self.channel_layer.group_discard(GROUP, self.channel_name)
        except Exception:  # noqa: BLE001 - disconnect must never raise
            pass

    async def alert_created(self, event):
        await self.send(
            json.dumps({"type": "alert.created", "payload": event["payload"]})
        )
