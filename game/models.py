from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class GameRoom(models.Model):
    STATUS_WAITING = "waiting"
    STATUS_PLAYING = "playing"
    STATUS_FINISHED = "finished"

    STATUS_CHOICES = [
        (STATUS_WAITING, "Čeká na hráče"),
        (STATUS_PLAYING, "Probíhá"),
        (STATUS_FINISHED, "Ukončeno"),
    ]

    name = models.CharField(max_length=100)
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hosted_rooms")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_WAITING)
    max_players = models.IntegerField(default=4)
    starting_money = models.IntegerField(default=100)
    base_bet = models.IntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(default=timezone.now)
    game_state = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    @property
    def active_player_count(self):
        return self.players.filter(active=True).count()


class GameRoomPlayer(models.Model):
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name="players")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="room_memberships")
    seat_index = models.IntegerField()
    active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("room", "user")]
        ordering = ["seat_index"]

    def __str__(self):
        return f"{self.user.username} v {self.room.name} (místo {self.seat_index})"


class GameMessage(models.Model):
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    username = models.CharField(max_length=150)
    text = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def to_dict(self):
        return {
            "username": self.username,
            "text": self.text,
            "ts": self.created_at.strftime("%H:%M"),
        }


class GameResult(models.Model):
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name="results")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="game_results")
    won = models.BooleanField()
    final_money = models.IntegerField()
    starting_money = models.IntegerField(default=100)
    played_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-played_at"]

    @property
    def net_money(self):
        return self.final_money - self.starting_money

    def __str__(self):
        result = "vyhrál" if self.won else "prohrál"
        return f"{self.user.username} {result} v {self.room.name}"
