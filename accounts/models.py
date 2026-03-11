from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


def compute_level(net_money):
    """
    Level based on cumulative net profit/loss.
      Level  3 : net >= +300
      Level  2 : net >= +200
      Level  1 : net >  -200  (base)
      Level  0 : net >  -300
      Level -1 : net <= -300
    """
    if net_money >= 300:
        return 3
    elif net_money >= 200:
        return 2
    elif net_money > -200:
        return 1
    elif net_money > -300:
        return 0
    else:
        return -1


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    games_played = models.IntegerField(default=0)
    games_won = models.IntegerField(default=0)

    def __str__(self):
        return f"Profil {self.user.username}"

    @property
    def games_lost(self):
        return self.games_played - self.games_won

    @property
    def win_rate(self):
        if self.games_played == 0:
            return 0.0
        return round(self.games_won / self.games_played * 100, 1)

    @property
    def net_money(self):
        from django.db.models import Sum, F
        from game.models import GameResult
        result = GameResult.objects.filter(user=self.user).aggregate(
            net=Sum(F("final_money") - F("starting_money"))
        )
        return result["net"] or 0

    @property
    def level(self):
        return compute_level(self.net_money)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, "profile"):
        instance.profile.save()
