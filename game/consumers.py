import json
import asyncio
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import models as django_models

from .game_logic import create_game_state, process_action

logger = logging.getLogger(__name__)

TURN_TIMEOUT = 5 * 60  # seconds

# Per-room asyncio tasks (module-level, single-process safe)
_turn_timers: dict[int, asyncio.Task] = {}


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

        # Send current state + recent chat messages to this client
        data = await self.get_room_data()
        await self.send(text_data=json.dumps(data))

        recent = await self.get_recent_messages()
        if recent:
            await self.send(text_data=json.dumps({"type": "chat_history", "messages": recent}))

        # Notify others that a player connected
        await self.broadcast_room_update()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await self.mark_player_active(False)
        await self.update_room_activity_if_empty()
        await self.broadcast_room_update()

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        from .models import GameRoom

        # Chat is allowed regardless of room status
        if action == "send_chat":
            await self.handle_chat(data)
            return

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

        state = create_game_state(players, starting_money=room.starting_money, base_bet=room.base_bet)
        await self.set_room_playing(state)

        levels = await self.get_player_levels(state["players"])
        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "game_state_broadcast", "state": state, "levels": levels},
        )
        await self._schedule_turn_timeout(state)

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

        levels = await self.get_player_levels(state["players"])
        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "game_state_broadcast", "state": state, "levels": levels},
        )
        await self._schedule_turn_timeout(state)

    # ── Chat ─────────────────────────────────────────────────────────────────

    async def handle_chat(self, data):
        text = str(data.get("text", "")).strip()[:500]
        if not text:
            return
        msg = await self.save_chat_message(text)
        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "chat_message_broadcast", "message": msg},
        )

    async def chat_message_broadcast(self, event):
        await self.send(text_data=json.dumps({"type": "chat_message", "message": event["message"]}))

    # ── Turn timeout ──────────────────────────────────────────────────────────

    async def _schedule_turn_timeout(self, state):
        room_id = int(self.room_id)
        if room_id in _turn_timers:
            _turn_timers[room_id].cancel()
            del _turn_timers[room_id]

        if state.get("phase") == "game-over":
            return

        expected_player_idx = state["current"]
        consumer_ref = self

        async def _timeout():
            try:
                await asyncio.sleep(TURN_TIMEOUT)
                await consumer_ref._apply_turn_timeout(room_id, expected_player_idx)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Chyba v turn timeout pro místnost %s", room_id)

        _turn_timers[room_id] = asyncio.create_task(_timeout())

    async def _apply_turn_timeout(self, room_id, expected_player_idx):
        from .models import GameRoom
        from .game_logic import _get_active_players, _check_game_over, _next_player_internal, _add_log

        room = await self._get_room_by_id(room_id)
        if not room or room.status != GameRoom.STATUS_PLAYING:
            return

        state = room.game_state
        if not state or state.get("current") != expected_player_idx:
            return  # Turn already changed

        current_player = state["players"][expected_player_idx]
        penalty = current_player["money"]
        current_player["money"] = 0
        state["bank"] += penalty
        current_player["eliminated"] = True
        _add_log(state, f"⏰ {current_player['name']} byl vyřazen pro nečinnost (−{penalty} Kč).", "loss")

        if not _check_game_over(state):
            _next_player_internal(state)

        await self._save_game_state_by_id(room_id, state)
        if state.get("phase") == "game-over":
            await self._save_game_results_by_id(room_id, state)

        levels = await self.get_player_levels(state["players"])
        await self.channel_layer.group_send(
            f"game_{room_id}",
            {"type": "game_state_broadcast", "state": state, "levels": levels},
        )

    # ── Channel layer message handlers ────────────────────────────────────────

    async def game_state_broadcast(self, event):
        try:
            await self.send(text_data=json.dumps({
                "type": "state_update",
                "state": event["state"],
                "levels": event.get("levels", {}),
            }))
        except Exception:
            pass

    async def room_update_broadcast(self, event):
        try:
            await self.send(text_data=json.dumps({"type": "room_update", "room": event["room"]}))
        except Exception:
            pass

    async def room_deleted_broadcast(self, event):
        try:
            await self.send(text_data=json.dumps({"type": "room_deleted"}))
        except Exception:
            pass

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
        from game.models import GameResult
        from accounts.models import compute_level
        from django.db.models import Sum, F

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
            return {"type": "state_update", "state": room.game_state, "levels": {}}

        player_ids = [p["user__id"] for p in players]
        net_by_user = {
            r["user_id"]: r["net"]
            for r in GameResult.objects.filter(user_id__in=player_ids)
            .values("user_id")
            .annotate(net=Sum(F("final_money") - F("starting_money")))
        }

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
                        "level": compute_level(net_by_user.get(p["user__id"], 0)),
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
    def get_player_levels(self, players):
        from game.models import GameResult
        from accounts.models import compute_level
        from django.db.models import Sum, F

        user_ids = [p["user_id"] for p in players]
        net_by_user = {
            r["user_id"]: r["net"]
            for r in GameResult.objects.filter(user_id__in=user_ids)
            .values("user_id")
            .annotate(net=Sum(F("final_money") - F("starting_money")))
        }
        return {uid: compute_level(net_by_user.get(uid, 0)) for uid in user_ids}

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
        starting_money = room.starting_money
        results = [
            GameResult(
                room=room,
                user_id=p["user_id"],
                won=(p["user_id"] == winner_id),
                final_money=p["money"],
                starting_money=starting_money,
            )
            for p in state["players"]
        ]
        GameResult.objects.bulk_create(results)

        for p in state["players"]:
            UserProfile.objects.filter(user_id=p["user_id"]).update(
                games_played=django_models.F("games_played") + 1,
                games_won=django_models.F("games_won") + (1 if p["user_id"] == winner_id else 0),
            )

    @database_sync_to_async
    def save_chat_message(self, text):
        from .models import GameMessage
        msg = GameMessage.objects.create(
            room_id=self.room_id,
            user=self.user,
            username=self.user.username,
            text=text,
        )
        return msg.to_dict()

    @database_sync_to_async
    def get_recent_messages(self):
        from .models import GameMessage
        msgs = GameMessage.objects.filter(room_id=self.room_id).order_by("-created_at")[:50]
        return [m.to_dict() for m in reversed(list(msgs))]

    @database_sync_to_async
    def _get_room_by_id(self, room_id):
        from .models import GameRoom
        try:
            return GameRoom.objects.get(id=room_id)
        except GameRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def _save_game_state_by_id(self, room_id, state):
        from .models import GameRoom
        new_status = (
            GameRoom.STATUS_FINISHED if state.get("phase") == "game-over" else GameRoom.STATUS_PLAYING
        )
        GameRoom.objects.filter(id=room_id).update(status=new_status, game_state=state)

    @database_sync_to_async
    def _save_game_results_by_id(self, room_id, state):
        from .models import GameRoom, GameResult
        from accounts.models import UserProfile
        try:
            room = GameRoom.objects.get(id=room_id)
        except GameRoom.DoesNotExist:
            return
        winner_id = state.get("winner_id")
        starting_money = room.starting_money
        results = [
            GameResult(
                room=room,
                user_id=p["user_id"],
                won=(p["user_id"] == winner_id),
                final_money=p["money"],
                starting_money=starting_money,
            )
            for p in state["players"]
        ]
        GameResult.objects.bulk_create(results)
        for p in state["players"]:
            UserProfile.objects.filter(user_id=p["user_id"]).update(
                games_played=django_models.F("games_played") + 1,
                games_won=django_models.F("games_won") + (1 if p["user_id"] == winner_id else 0),
            )

    @database_sync_to_async
    def update_room_activity_if_empty(self):
        from .models import GameRoom, GameRoomPlayer
        from django.utils import timezone

        if not GameRoomPlayer.objects.filter(room_id=self.room_id, active=True).exists():
            GameRoom.objects.filter(id=self.room_id, status=GameRoom.STATUS_WAITING).update(
                last_activity=timezone.now()
            )
