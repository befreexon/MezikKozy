import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import models as django_models

from .game_logic import create_game_state, process_action


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_name = f"game_{self.room_id}"
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            await self.close()
            return

        is_member = await self.is_room_member()
        if not is_member:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.mark_player_active(True)

        # Send current state to this client
        data = await self.get_room_data()
        await self.send(text_data=json.dumps(data))

        # Notify others that a player connected
        await self.broadcast_room_update()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await self.mark_player_active(False)
        await self.broadcast_room_update()

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        from .models import GameRoom

        room = await self.get_room()
        if room is None:
            return

        if room.status == GameRoom.STATUS_WAITING:
            if action == "start_game":
                await self.handle_start_game(room)

        elif room.status == GameRoom.STATUS_PLAYING:
            await self.handle_game_action(room, action, data)

    # ── Action handlers ───────────────────────────────────────────────────────

    async def handle_start_game(self, room):
        if self.user.id != room.host_id:
            return

        players = await self.get_ordered_players()
        if len(players) < 2:
            await self.send(
                text_data=json.dumps({"type": "error", "message": "Potřebujete alespoň 2 hráče!"})
            )
            return

        state = create_game_state(players)
        await self.set_room_playing(state)

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "game_state_broadcast", "state": state},
        )

    async def handle_game_action(self, room, action, data):
        state = room.game_state
        if state is None:
            return

        current_user_id = state["players"][state["current"]]["user_id"]
        if self.user.id != current_user_id:
            return

        success = process_action(state, action, data)
        if not success:
            return

        await self.save_game_state(state)

        if state.get("phase") == "game-over":
            await self.save_game_results(state)

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "game_state_broadcast", "state": state},
        )

    # ── Channel layer message handlers ────────────────────────────────────────

    async def game_state_broadcast(self, event):
        await self.send(text_data=json.dumps({"type": "state_update", "state": event["state"]}))

    async def room_update_broadcast(self, event):
        await self.send(text_data=json.dumps({"type": "room_update", "room": event["room"]}))

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def broadcast_room_update(self):
        data = await self.get_room_data()
        if data.get("type") == "room_update":
            await self.channel_layer.group_send(
                self.room_group_name,
                {"type": "room_update_broadcast", "room": data["room"]},
            )

    # ── DB helpers (sync wrappers) ────────────────────────────────────────────

    @database_sync_to_async
    def get_room(self):
        from .models import GameRoom

        try:
            return GameRoom.objects.get(id=self.room_id)
        except GameRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def is_room_member(self):
        from .models import GameRoomPlayer

        return GameRoomPlayer.objects.filter(room_id=self.room_id, user=self.user).exists()

    @database_sync_to_async
    def get_room_data(self):
        from .models import GameRoom

        try:
            room = GameRoom.objects.get(id=self.room_id)
        except GameRoom.DoesNotExist:
            return {"type": "error", "message": "Místnost nenalezena"}

        players = list(
            room.players.select_related("user").order_by("seat_index").values(
                "user__id", "user__username", "seat_index", "active"
            )
        )

        if room.status == GameRoom.STATUS_PLAYING and room.game_state:
            return {"type": "state_update", "state": room.game_state}

        return {
            "type": "room_update",
            "room": {
                "id": room.id,
                "name": room.name,
                "status": room.status,
                "host_id": room.host_id,
                "max_players": room.max_players,
                "players": [
                    {
                        "id": p["user__id"],
                        "username": p["user__username"],
                        "seat": p["seat_index"],
                        "active": p["active"],
                    }
                    for p in players
                ],
            },
        }

    @database_sync_to_async
    def get_ordered_players(self):
        from .models import GameRoomPlayer

        players = (
            GameRoomPlayer.objects.filter(room_id=self.room_id, active=True)
            .select_related("user")
            .order_by("seat_index")
        )
        return [{"name": p.user.username, "user_id": p.user.id} for p in players]

    @database_sync_to_async
    def mark_player_active(self, active):
        from .models import GameRoomPlayer

        GameRoomPlayer.objects.filter(room_id=self.room_id, user=self.user).update(active=active)

    @database_sync_to_async
    def set_room_playing(self, state):
        from .models import GameRoom

        GameRoom.objects.filter(id=self.room_id).update(status=GameRoom.STATUS_PLAYING, game_state=state)

    @database_sync_to_async
    def save_game_state(self, state):
        from .models import GameRoom

        new_status = (
            GameRoom.STATUS_FINISHED if state.get("phase") == "game-over" else GameRoom.STATUS_PLAYING
        )
        GameRoom.objects.filter(id=self.room_id).update(status=new_status, game_state=state)

    @database_sync_to_async
    def save_game_results(self, state):
        from .models import GameRoom, GameResult
        from accounts.models import UserProfile

        try:
            room = GameRoom.objects.get(id=self.room_id)
        except GameRoom.DoesNotExist:
            return

        winner_id = state.get("winner_id")
        results = [
            GameResult(
                room=room,
                user_id=p["user_id"],
                won=(p["user_id"] == winner_id),
                final_money=p["money"],
            )
            for p in state["players"]
        ]
        GameResult.objects.bulk_create(results)

        for p in state["players"]:
            UserProfile.objects.filter(user_id=p["user_id"]).update(
                games_played=django_models.F("games_played") + 1,
                games_won=django_models.F("games_won") + (1 if p["user_id"] == winner_id else 0),
            )
