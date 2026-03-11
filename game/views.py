from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Exists, OuterRef
from django.utils import timezone
from datetime import timedelta

from .models import GameRoom, GameRoomPlayer


def _cleanup_stale_rooms():
    """Smaže waiting místnosti bez aktivních hráčů starší 5 minut."""
    cutoff = timezone.now() - timedelta(minutes=5)
    active_players = GameRoomPlayer.objects.filter(room=OuterRef("pk"), active=True)
    GameRoom.objects.filter(
        status=GameRoom.STATUS_WAITING,
        last_activity__lt=cutoff,
    ).exclude(Exists(active_players)).delete()


@login_required
def home(request):
    _cleanup_stale_rooms()
    rooms = GameRoom.objects.filter(status__in=[GameRoom.STATUS_WAITING, GameRoom.STATUS_PLAYING]).select_related(
        "host"
    )
    return render(request, "home.html", {"rooms": rooms})


@login_required
def create_room(request):
    if request.method != "POST":
        return redirect("game:home")

    name = request.POST.get("name", "").strip() or f"Místnost {request.user.username}"

    try:
        starting_money = max(10, min(10000, int(request.POST.get("starting_money", 100))))
    except (ValueError, TypeError):
        starting_money = 100

    try:
        base_bet = max(1, min(starting_money // 2, int(request.POST.get("base_bet", 10))))
    except (ValueError, TypeError):
        base_bet = 10

    room = GameRoom.objects.create(
        name=name,
        host=request.user,
        starting_money=starting_money,
        base_bet=base_bet,
    )
    GameRoomPlayer.objects.create(room=room, user=request.user, seat_index=0, active=True)
    return redirect("game:lobby", room_id=room.id)


@login_required
def delete_room(request, room_id):
    room = get_object_or_404(GameRoom, id=room_id)
    if request.method == "POST" and room.host == request.user and room.status == GameRoom.STATUS_WAITING:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        async_to_sync(get_channel_layer().group_send)(
            f"game_{room_id}",
            {"type": "room_deleted_broadcast"},
        )
        room.delete()
    return redirect("game:home")


@login_required
def rooms_api(request):
    from django.http import JsonResponse
    _cleanup_stale_rooms()
    rooms = GameRoom.objects.filter(
        status__in=[GameRoom.STATUS_WAITING, GameRoom.STATUS_PLAYING]
    ).select_related("host")
    data = [
        {
            "id": r.id,
            "name": r.name,
            "host": r.host.username,
            "status": r.status,
            "player_count": r.active_player_count,
            "max_players": r.max_players,
            "starting_money": r.starting_money,
            "base_bet": r.base_bet,
        }
        for r in rooms
    ]
    return JsonResponse({"rooms": data})


@login_required
def join_room(request, room_id):
    room = get_object_or_404(GameRoom, id=room_id)

    # Already a member – route to correct page
    existing = GameRoomPlayer.objects.filter(room=room, user=request.user).first()
    if existing:
        if room.status == GameRoom.STATUS_PLAYING:
            return redirect("game:game", room_id=room.id)
        return redirect("game:lobby", room_id=room.id)

    if room.status != GameRoom.STATUS_WAITING:
        return redirect("game:home")

    if room.active_player_count >= room.max_players:
        return redirect("game:home")

    max_seat = room.players.aggregate(Max("seat_index"))["seat_index__max"]
    seat_index = (max_seat or -1) + 1

    GameRoomPlayer.objects.create(room=room, user=request.user, seat_index=seat_index, active=True)
    GameRoom.objects.filter(id=room_id).update(last_activity=timezone.now())
    return redirect("game:lobby", room_id=room.id)


@login_required
def lobby(request, room_id):
    room = get_object_or_404(GameRoom, id=room_id)

    if not GameRoomPlayer.objects.filter(room=room, user=request.user).exists():
        return redirect("game:home")

    if room.status == GameRoom.STATUS_PLAYING:
        return redirect("game:game", room_id=room.id)

    players = room.players.filter(active=True).select_related("user").order_by("seat_index")

    return render(
        request,
        "game/lobby.html",
        {
            "room": room,
            "players": players,
            "is_host": room.host_id == request.user.id,
        },
    )


def rules(request):
    return render(request, "game/rules.html")


@login_required
def game_view(request, room_id):
    room = get_object_or_404(GameRoom, id=room_id)

    if not GameRoomPlayer.objects.filter(room=room, user=request.user).exists():
        return redirect("game:home")

    if room.status == GameRoom.STATUS_WAITING:
        return redirect("game:lobby", room_id=room.id)

    return render(
        request,
        "game/game.html",
        {
            "room": room,
            "current_user_id": request.user.id,
        },
    )
