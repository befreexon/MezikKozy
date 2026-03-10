from django.urls import path
from . import views

app_name = "game"

urlpatterns = [
    path("", views.home, name="home"),
    path("create/", views.create_room, name="create_room"),
    path("join/<int:room_id>/", views.join_room, name="join_room"),
    path("room/<int:room_id>/", views.lobby, name="lobby"),
    path("room/<int:room_id>/play/", views.game_view, name="game"),
]
