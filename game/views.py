from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Max

from .models import GameRoom, GameRoomPlayer


@login_required
def home(request):
    rooms = GameRoom.objects.filter(status__in=[GameRoom.STATUS_WAITING, GameRoom.STATUS_PLAYING]).select_related(
        "host"
    )
    return render(request, "home.html", {"rooms": rooms})


@login_required
def create_room(request):
    if request.method != "POST":
        return redirect("game:home")
    name = request.POST.get("name", "").strip() or f"Místnost {request.user.username}"
    room = GameRoom.objects.create(name=name, host=request.user)
    GameRoomPlayer.objects.create(room=room, user=request.user, seat_index=0, active=True)
    return redirect("game:lobby", room_id=room.id)


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
